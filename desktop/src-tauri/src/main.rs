// Kerf: the background helper the installer sets up. It has no window: it puts the Kerf panels into Premiere Pro,
// After Effects and DaVinci Resolve, runs the local engine while an editor is open, and keeps Kerf up to date.
// The panels start it when they open; it quits (installing any downloaded update) after the editors close.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::{
    fs,
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, Command},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tauri::{Manager, RunEvent};
use tauri_plugin_updater::{Update, UpdaterExt};

struct Engine(Arc<Mutex<Option<Child>>>);

/// A downloaded, signature-checked update waiting for Kerf to quit.
struct Staged(Mutex<Option<(Update, Vec<u8>)>>);

fn home() -> Option<PathBuf> {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).map(PathBuf::from)
}

/// ~/.kerf (settings, token, logs), or KERF_HOME_DIR.
fn kerf_dir() -> Option<PathBuf> {
    std::env::var_os("KERF_HOME_DIR").map(PathBuf::from).or_else(|| home().map(|h| h.join(".kerf")))
}

/// Settings → Automatic updates (`auto_update` in ~/.kerf/settings.json); on unless switched off.
fn auto_update_on() -> bool {
    kerf_dir()
        .and_then(|k| fs::read_to_string(k.join("settings.json")).ok())
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .map_or(true, |v| v.get("auto_update").and_then(|x| x.as_str()) != Some("off"))
}

/// Check GitHub for a newer release shortly after launch and every 6 hours; download it in the background.
/// It is installed when Kerf quits (after the editors close), so nobody loses work to a surprise restart.
async fn update_loop(app: tauri::AppHandle) {
    tokio::time::sleep(Duration::from_secs(20)).await;
    loop {
        if auto_update_on() {
            let found: Result<Option<Update>, tauri_plugin_updater::Error> = async { app.updater()?.check().await }.await;
            if let Ok(Some(update)) = found {
                if let Ok(bytes) = update.download(|_, _| {}, || {}).await {
                    *app.state::<Staged>().0.lock().unwrap() = Some((update, bytes));
                    return;
                }
            }
        }
        tokio::time::sleep(Duration::from_secs(6 * 3600)).await;
    }
}

fn engine_up() -> bool {
    TcpStream::connect_timeout(&"127.0.0.1:7878".parse().unwrap(), Duration::from_millis(300)).is_ok()
}

fn io_err(e: impl ToString) -> std::io::Error {
    std::io::Error::other(e.to_string())
}

/// No console window flashing up for helper processes on Windows.
fn quiet(cmd: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    cmd
}

/// Folder holding the kerf-engine executable. Windows/macOS bundle it as a folder; Linux ships one archive
/// (keeps AppImage tooling away from the engine's libraries) that is unpacked once per version.
fn engine_dir(res: PathBuf, data: PathBuf, version: &str) -> std::io::Result<PathBuf> {
    let dir = res.join("engine");
    if dir.is_dir() {
        return Ok(dir);
    }
    let dest = data.join(format!("engine-{version}"));
    let unpacked = dest.join("kerf-engine");
    if !unpacked.is_dir() {
        fs::create_dir_all(&dest)?;
        let ok = Command::new("tar").arg("-xzf").arg(res.join("engine.tar.gz")).arg("-C").arg(&dest).status()?;
        if !ok.success() {
            let _ = fs::remove_dir_all(&unpacked); // never leave a half-unpacked engine behind
            return Err(io_err("could not unpack the engine"));
        }
    }
    Ok(unpacked)
}

fn start_engine(dir: PathBuf) -> std::io::Result<Child> {
    let exe = dir.join(if cfg!(windows) { "kerf-engine.exe" } else { "kerf-engine" });
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt; // bundlers don't always keep the exec bit on resources
        let _ = fs::set_permissions(&exe, fs::Permissions::from_mode(0o755));
    }
    let mut cmd = Command::new(&exe);
    cmd.args(["serve", "--follow-editors"]).current_dir(&dir).env("KERF_STUDIO", "1"); // engine: "Kerf updates itself"
    if let Ok(me) = std::env::current_exe() {
        cmd.env("KERF_HELPER", me); // written to the engine's locator, so every panel starts this same helper
    }
    quiet(&mut cmd).spawn()
}

fn copy_dir(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for e in fs::read_dir(src)? {
        let e = e?;
        let to = dst.join(e.file_name());
        if e.file_type()?.is_dir() {
            copy_dir(&e.path(), &to)?;
        } else {
            fs::copy(e.path(), &to)?;
        }
    }
    Ok(())
}

/// Adobe's plugin installer (ships with Creative Cloud): installs the Premiere .ccx the way a double-click would.
fn adobe_installer() -> Option<(PathBuf, &'static str)> {
    let p = if cfg!(windows) {
        PathBuf::from(r"C:\Program Files\Common Files\Adobe\Adobe Desktop Common\RemoteComponents\UPI\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe")
    } else {
        PathBuf::from("/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/UnifiedPluginInstallerAgent.app/Contents/MacOS/UnifiedPluginInstallerAgent")
    };
    p.is_file().then_some((p, if cfg!(windows) { "/install" } else { "--install" }))
}

fn cep_extensions() -> Option<PathBuf> {
    if cfg!(windows) {
        std::env::var_os("APPDATA").map(|a| PathBuf::from(a).join(r"Adobe\CEP\extensions"))
    } else if cfg!(target_os = "macos") {
        home().map(|h| h.join("Library/Application Support/Adobe/CEP/extensions"))
    } else {
        None // no After Effects on Linux
    }
}

fn resolve_scripts() -> Option<PathBuf> {
    if cfg!(windows) {
        std::env::var_os("APPDATA")
            .map(|a| PathBuf::from(a).join(r"Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility"))
    } else if cfg!(target_os = "macos") {
        home().map(|h| h.join("Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"))
    } else {
        home().map(|h| h.join(".local/share/DaVinciResolve/Fusion/Scripts/Utility"))
    }
}

/// Kerf has no window, so a Desktop shortcut to it is misleading. The Windows installer's finish page can still
/// create one after every install hook has run; drop it whenever the helper starts (only if it points at kerf.exe).
fn remove_desktop_shortcut() {
    if !cfg!(windows) {
        return;
    }
    for var in ["USERPROFILE", "OneDrive", "PUBLIC"] {
        if let Some(lnk) = std::env::var_os(var).map(|d| PathBuf::from(d).join("Desktop").join("Kerf.lnk")) {
            let ours = fs::read(&lnk).is_ok_and(|b| {
                let ascii = String::from_utf8_lossy(&b).to_lowercase();
                let wide: String = b.chunks_exact(2).map(|c| c[0] as char).collect::<String>().to_lowercase();
                ascii.contains("kerf.exe") || wide.contains("kerf.exe") // .lnk stores the target as ANSI or UTF-16
            });
            if ours {
                let _ = fs::remove_file(&lnk);
            }
        }
    }
}

/// Kerf FX, the OpenFX effects for Resolve's Edit, Color and Fusion pages. The standard OFX folders need admin
/// rights, so Kerf FX lives in a per-user folder that Resolve finds through OFX_PLUGIN_PATH.
fn ofx_dir() -> Option<PathBuf> {
    if cfg!(windows) {
        std::env::var_os("LOCALAPPDATA").map(|a| PathBuf::from(a).join(r"Kerf\OFX"))
    } else if cfg!(target_os = "macos") {
        home().map(|h| h.join("Library/Application Support/Kerf/OFX"))
    } else {
        home().map(|h| h.join(".local/share/kerf/OFX"))
    }
}

/// Adds the Kerf FX folder to the user's OFX_PLUGIN_PATH for apps started from now on (Resolve reads it at launch).
/// Reads the live user value each time, never this process's environment, which may be stale or hold the machine value.
fn add_ofx_path(dir: &Path) {
    let d = dir.to_string_lossy().to_string();
    if cfg!(windows) {
        // user scope, tells Explorer; unlike setx it never truncates long values (the folder travels via the env)
        let script = concat!(
            "$d = $env:KERF_OFX_DIR; $v = [Environment]::GetEnvironmentVariable('OFX_PLUGIN_PATH', 'User'); ",
            "$p = @(if ($v) { $v -split ';' | Where-Object { $_ } }); ",
            "if ($p -notcontains $d) { [Environment]::SetEnvironmentVariable('OFX_PLUGIN_PATH', (@($p) + $d) -join ';', 'User') }",
        );
        let _ = quiet(Command::new("powershell").args(["-NoProfile", "-NonInteractive", "-Command", script])
            .env("KERF_OFX_DIR", &d)).status();
    } else if cfg!(target_os = "macos") {
        let current = Command::new("launchctl").args(["getenv", "OFX_PLUGIN_PATH"]).output()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default();
        if current.split(':').any(|p| p == d) {
            return;
        }
        let value = if current.is_empty() { d.clone() } else { format!("{current}:{d}") };
        // apps launched from the Dock only see launchd's environment: set it now and at every login
        let _ = quiet(Command::new("launchctl").args(["setenv", "OFX_PLUGIN_PATH", &value])).status();
        if let Some(agents) = home().map(|h| h.join("Library/LaunchAgents")) {
            let value = value.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;"); // plist is XML
            let plist = format!(
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n<plist version=\"1.0\"><dict><key>Label</key><string>com.kerf.ofx-path</string><key>ProgramArguments</key><array><string>launchctl</string><string>setenv</string><string>OFX_PLUGIN_PATH</string><string>{value}</string></array><key>RunAtLoad</key><true/></dict></plist>\n"
            );
            let _ = fs::create_dir_all(&agents).and_then(|_| fs::write(agents.join("com.kerf.ofx-path.plist"), plist));
        }
    } else if let Some(conf) = home().map(|h| h.join(".config/environment.d")) {
        // environment.d expands the value at login, so other folders set elsewhere are kept as they are then
        let line = format!("OFX_PLUGIN_PATH=${{OFX_PLUGIN_PATH:+$OFX_PLUGIN_PATH:}}{d}\n");
        let _ = fs::create_dir_all(&conf).and_then(|_| fs::write(conf.join("kerf-ofx.conf"), line));
    }
}

/// Puts (or refreshes) the Kerf panel in every editor on this machine, once per Kerf version unless forced.
/// Kerf FX keeps its own marker: a bundle locked by a running Resolve retries alone, not the Adobe installs.
fn install_panels(res: &Path, version: &str, force: bool) {
    let p = res.join("panels");
    if force || !marked("panels-version", version) {
        let ccx = p.join("kerf-premiere.ccx");
        if let (Some((agent, flag)), true) = (adobe_installer(), ccx.is_file()) {
            let _ = quiet(Command::new(agent).arg(flag).arg(&ccx)).status(); // Premiere Pro
        }
        if let Some(dir) = cep_extensions() {
            let dest = dir.join("com.kerf.aftereffects"); // After Effects
            let _ = fs::remove_dir_all(&dest);
            let _ = copy_dir(&p.join("com.kerf.aftereffects"), &dest);
        }
        if let Some(dir) = resolve_scripts() {
            let _ = fs::create_dir_all(&dir).and_then(|_| fs::copy(p.join("Kerf.py"), dir.join("Kerf.py")).map(|_| ()));
        }
        mark("panels-version", version);
    }
    let fx = p.join("KerfFX.ofx.bundle");
    if let (Some(dir), true, true) = (ofx_dir(), fx.is_dir(), force || !marked("ofx-version", version)) {
        // Resolve: Effects > OpenFX > Kerf (after Resolve restarts). Copy beside the old bundle, then swap, so a
        // bundle locked by a running Resolve stays usable and the swap is retried on the next start.
        let (dest, new, old) = (dir.join("KerfFX.ofx.bundle"), dir.join("KerfFX.ofx.bundle.new"), dir.join("KerfFX.ofx.bundle.old"));
        let _ = fs::remove_dir_all(&new);
        let _ = fs::remove_dir_all(&old);
        let ok = copy_dir(&fx, &new).is_ok() && (!dest.exists() || fs::rename(&dest, &old).is_ok()) && fs::rename(&new, &dest).is_ok();
        if !ok && !dest.exists() && old.exists() {
            let _ = fs::rename(&old, &dest); // put the previous Kerf FX back
        }
        let _ = fs::remove_dir_all(if ok { &old } else { &new });
        if ok {
            add_ofx_path(&dir);
            mark("ofx-version", version);
        }
    }
}

/// Takes Kerf out of every editor: the exact mirror of install_panels, with the same paths. Run by the uninstaller.
fn remove_panels() {
    if let Some((agent, _)) = adobe_installer() {
        // ponytail: UPIA removes by the plugin's manifest name ("Kerf"); confirm on a machine with Creative Cloud
        let _ = quiet(Command::new(agent).arg(if cfg!(windows) { "/remove" } else { "--remove" }).arg("Kerf")).status();
    }
    if let Some(dir) = cep_extensions() {
        let _ = fs::remove_dir_all(dir.join("com.kerf.aftereffects"));
    }
    if let Some(dir) = resolve_scripts() {
        let _ = fs::remove_file(dir.join("Kerf.py"));
    }
    if let Some(dir) = ofx_dir() {
        remove_ofx_path(&dir);
        let _ = fs::remove_dir_all(&dir);
    }
    if let Some(k) = kerf_dir() {
        for m in ["panels-version", "ofx-version"] {
            let _ = fs::remove_file(k.join(m));
        }
    }
}

/// Takes the Kerf FX folder out of the user's OFX_PLUGIN_PATH, keeping every other plugin's folder.
fn remove_ofx_path(dir: &Path) {
    let d = dir.to_string_lossy().to_string();
    if cfg!(windows) {
        let script = concat!(
            "$d = $env:KERF_OFX_DIR; $v = [Environment]::GetEnvironmentVariable('OFX_PLUGIN_PATH', 'User'); ",
            "if ($v) { $p = @($v -split ';' | Where-Object { $_ -and $_.TrimEnd('\\') -ne $d }); ",
            "[Environment]::SetEnvironmentVariable('OFX_PLUGIN_PATH', $(if ($p) { $p -join ';' } else { $null }), 'User') }",
        );
        let _ = quiet(Command::new("powershell").args(["-NoProfile", "-NonInteractive", "-Command", script])
            .env("KERF_OFX_DIR", &d)).status();
    } else if cfg!(target_os = "macos") {
        let current = Command::new("launchctl").args(["getenv", "OFX_PLUGIN_PATH"]).output()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string()).unwrap_or_default();
        let rest: Vec<&str> = current.split(':').filter(|p| !p.is_empty() && *p != d).collect();
        let _ = if rest.is_empty() {
            quiet(Command::new("launchctl").args(["unsetenv", "OFX_PLUGIN_PATH"])).status()
        } else {
            quiet(Command::new("launchctl").args(["setenv", "OFX_PLUGIN_PATH", &rest.join(":")])).status()
        };
        if let Some(h) = home() {
            let _ = fs::remove_file(h.join("Library/LaunchAgents/com.kerf.ofx-path.plist"));
        }
    } else if let Some(h) = home() {
        let _ = fs::remove_file(h.join(".config/environment.d/kerf-ofx.conf"));
    }
}

fn marked(name: &str, version: &str) -> bool {
    kerf_dir().and_then(|k| fs::read_to_string(k.join(name)).ok()).as_deref() == Some(version)
}

fn mark(name: &str, version: &str) {
    if let Some(k) = kerf_dir() {
        let _ = fs::create_dir_all(&k).and_then(|_| fs::write(k.join(name), version));
    }
}

fn main() {
    if std::env::args().any(|a| a == "--remove-panels") {
        remove_panels(); // run by the uninstaller: no window, no engine
        return;
    }
    let install_only = std::env::args().any(|a| a == "--install-panels"); // run by the installer
    let child = Arc::new(Mutex::new(None));
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Engine(child.clone()))
        .manage(Staged(Mutex::new(None)))
        .setup(move |app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory); // background helper: no Dock icon
            remove_desktop_shortcut();
            let res = app.path().resource_dir().map_err(io_err)?;
            let version = app.package_info().version.to_string();
            if install_only {
                install_panels(&res, &version, true);
                std::process::exit(0);
            }
            if engine_up() {
                // Another Kerf already serves the panels; just make sure they match this version.
                install_panels(&res, &version, false);
                std::process::exit(0);
            }
            let (r2, v2) = (res.clone(), version.clone());
            std::thread::spawn(move || install_panels(&r2, &v2, false)); // after an update: refresh the panels
            tauri::async_runtime::spawn(update_loop(app.handle().clone()));
            // Kerf runs alongside an editor: the engine stops ~1 min after the last one closes (unless switched
            // off in Settings), and once it is gone Kerf quits too. An engine that never answers also ends it.
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let (mut seen, mut misses, started) = (false, 0, Instant::now());
                loop {
                    std::thread::sleep(Duration::from_secs(3));
                    if engine_up() {
                        (seen, misses) = (true, 0);
                    } else if seen || started.elapsed() > Duration::from_secs(180) {
                        misses += 1;
                        if misses >= 2 {
                            handle.exit(0);
                            return;
                        }
                    }
                }
            });
            let data = app.path().app_local_data_dir().map_err(io_err)?;
            std::thread::spawn(move || match engine_dir(res, data, &version).and_then(start_engine) {
                Ok(c) => *child.lock().unwrap() = Some(c),
                Err(e) => eprintln!("kerf: could not start the engine: {e}"),
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("kerf: failed to start")
        .run(|app, event| match event {
            RunEvent::ExitRequested { api, code: None, .. } => api.prevent_exit(), // no windows: stay until we exit
            RunEvent::Exit => {
                if let Some(mut c) = app.state::<Engine>().0.lock().unwrap().take() {
                    let _ = c.kill(); // only the engine we started
                }
                if let Some((update, bytes)) = app.state::<Staged>().0.lock().unwrap().take() {
                    let _ = update.install(bytes); // engine stopped, so its files can be replaced
                }
            }
            _ => {}
        });
}
