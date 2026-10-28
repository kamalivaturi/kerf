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

/// Kerf FX, the OpenFX effects for Resolve's Edit, Color and Fusion pages, live in the standard OFX folder: Resolve 21
/// lists plugins only from there (it ignores OFX_PLUGIN_PATH). Writing it needs admin rights, asked once per version.
fn ofx_dir() -> PathBuf {
    if cfg!(windows) {
        let common = std::env::var_os("CommonProgramFiles").map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(r"C:\Program Files\Common Files"));
        common.join(r"OFX\Plugins")
    } else if cfg!(target_os = "macos") {
        PathBuf::from("/Library/OFX/Plugins")
    } else {
        PathBuf::from("/usr/OFX/Plugins")
    }
}

/// Where Kerf 0.3.2 put Kerf FX (per user, found through OFX_PLUGIN_PATH). Taken out so Resolve sees one Kerf FX.
fn old_ofx_dir() -> Option<PathBuf> {
    if cfg!(windows) {
        std::env::var_os("LOCALAPPDATA").map(|a| PathBuf::from(a).join(r"Kerf\OFX"))
    } else if cfg!(target_os = "macos") {
        home().map(|h| h.join("Library/Application Support/Kerf/OFX"))
    } else {
        home().map(|h| h.join(".local/share/kerf/OFX"))
    }
}

fn remove_old_ofx() {
    if let Some(dir) = old_ofx_dir() {
        remove_ofx_path(&dir);
        let _ = fs::remove_dir_all(&dir);
    }
}

/// Puts the bundle in the OFX folder: copied beside the old one, then swapped, so a bundle locked by a running
/// Resolve stays usable and the swap is retried on the next start. True once the new Kerf FX is in place.
fn swap_ofx(fx: &Path, dir: &Path) -> bool {
    let (dest, new, old) = (dir.join("KerfFX.ofx.bundle"), dir.join("KerfFX.ofx.bundle.new"), dir.join("KerfFX.ofx.bundle.old"));
    let _ = fs::create_dir_all(dir);
    let _ = fs::remove_dir_all(&new);
    let _ = fs::remove_dir_all(&old);
    let ok = copy_dir(fx, &new).is_ok() && (!dest.exists() || fs::rename(&dest, &old).is_ok()) && fs::rename(&new, &dest).is_ok();
    if !ok && !dest.exists() && old.exists() {
        let _ = fs::rename(&old, &dest); // put the previous Kerf FX back
    }
    let _ = fs::remove_dir_all(if ok { &old } else { &new });
    ok
}

/// Takes Kerf FX (only its own bundle) out of the OFX folder other plugins share. True when it is gone.
fn remove_ofx_bundle() -> bool {
    let dir = ofx_dir();
    for b in ["KerfFX.ofx.bundle", "KerfFX.ofx.bundle.new", "KerfFX.ofx.bundle.old"] {
        let _ = fs::remove_dir_all(dir.join(b));
    }
    !dir.join("KerfFX.ofx.bundle").exists()
}

/// Exit code of an admin-only step that failed but should be retried (a running Resolve holds the bundle).
const RETRY: i32 = 3;

/// Runs this helper again with admin rights for one step (--install-ofx / --remove-ofx) and waits. Some(code) when
/// the step ran; None when the person declined the admin prompt or it could not be shown.
fn elevated(args: &[&str]) -> Option<i32> {
    let me = std::env::current_exe().ok()?.to_string_lossy().to_string();
    let code = if cfg!(windows) {
        // the arguments travel through the environment, so paths with spaces or quotes need no escaping
        let script = "try { $p = Start-Process -FilePath $env:KERF_ME -ArgumentList $env:KERF_ARGS -Verb RunAs -Wait -PassThru; \
                      exit $p.ExitCode } catch { exit 99 }";
        let quoted: Vec<String> = args.iter().map(|a| format!("\"{a}\"")).collect();
        quiet(Command::new("powershell").args(["-NoProfile", "-NonInteractive", "-Command", script])
            .env("KERF_ME", &me).env("KERF_ARGS", quoted.join(" "))).status().ok()?.code()?
    } else if cfg!(target_os = "macos") {
        let q = |a: &str| format!("'{}'", a.replace('\'', "'\\''")); // sh quoting inside AppleScript's string
        let sh = std::iter::once(q(&me)).chain(args.iter().map(|a| q(a))).collect::<Vec<_>>().join(" ");
        let apple = format!("do shell script \"{}\" with administrator privileges", sh.replace('\\', "\\\\").replace('"', "\\\""));
        Command::new("osascript").args(["-e", &apple]).status().ok()?.code()?
    } else {
        Command::new("pkexec").arg(&me).args(args).status().ok()?.code()?
    };
    // 99 (Windows), 1 (macOS, cancelled) and 126/127 (pkexec) mean the step never ran
    if [99, 126, 127].contains(&code) || (cfg!(target_os = "macos") && code == 1) { None } else { Some(code) }
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
            let _ = fs::remove_file(dir.join("Kerf.py")); // Kerf in Resolve is Kerf FX only now: drop the old script window
        }
        mark("panels-version", version);
    }
    let fx = p.join("KerfFX.ofx.bundle");
    let due = force || !(marked("ofx-version", version) || marked("ofx-asked", version));
    if fx.is_dir() && due {
        // Resolve: Effects > OpenFX > Kerf (after Resolve restarts). The OFX folder usually needs admin rights: try
        // as this user first, then ask once. A declined prompt waits for the next version or a reinstall.
        let done = swap_ofx(&fx, &ofx_dir()) || match elevated(&["--install-ofx", &fx.to_string_lossy()]) {
            Some(0) => true,
            Some(_) => false, // ran but couldn't swap (Resolve open): try again on the next start
            None => {
                mark("ofx-asked", version);
                false
            }
        };
        if done {
            remove_old_ofx();
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
    if !remove_ofx_bundle() {
        let _ = elevated(&["--remove-ofx"]); // the OFX folder needs admin rights
    }
    remove_old_ofx();
    if let Some(k) = kerf_dir() {
        for m in ["panels-version", "ofx-version", "ofx-asked"] {
            let _ = fs::remove_file(k.join(m));
        }
    }
}

/// Takes 0.3.2's Kerf FX folder out of the user's OFX_PLUGIN_PATH, keeping every other plugin's folder.
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
    let args: Vec<String> = std::env::args().collect();
    if let Some(i) = args.iter().position(|a| a == "--install-ofx") {
        // the one admin step, run elevated by install_panels: copy Kerf FX into the OFX folder
        let ok = args.get(i + 1).is_some_and(|src| swap_ofx(Path::new(src), &ofx_dir()));
        std::process::exit(if ok { 0 } else { RETRY });
    }
    if args.iter().any(|a| a == "--remove-ofx") {
        std::process::exit(if remove_ofx_bundle() { 0 } else { RETRY }); // elevated by remove_panels
    }
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
