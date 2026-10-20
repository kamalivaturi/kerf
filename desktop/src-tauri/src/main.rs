// Kerf Studio: native shell around the Kerf engine. Starts the bundled engine (unless one is already
// running, e.g. for the Premiere panel), shows the splash until it answers, then the app UI at /app/.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::{
    net::TcpStream,
    path::PathBuf,
    process::{Child, Command},
    sync::{Arc, Mutex},
    time::Duration,
};
use tauri::{Manager, RunEvent};
use tauri_plugin_updater::{Update, UpdaterExt};

struct Engine(Arc<Mutex<Option<Child>>>);

/// A downloaded, signature-checked update waiting for the app to quit.
struct Staged(Mutex<Option<(Update, Vec<u8>)>>);

/// Settings → Automatic updates (`auto_update` in ~/.kerf/settings.json); on unless switched off.
fn auto_update_on() -> bool {
    let kerf = std::env::var_os("KERF_HOME_DIR")
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
                .map(|h| PathBuf::from(h).join(".kerf"))
        });
    kerf.and_then(|k| std::fs::read_to_string(k.join("settings.json")).ok())
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .map_or(true, |v| {
            v.get("auto_update").and_then(|x| x.as_str()) != Some("off")
        })
}

/// Check GitHub for a newer release shortly after launch and every 6 hours; download it in the background.
/// It is installed when the user quits, so nobody loses work to a surprise restart.
async fn update_loop(app: tauri::AppHandle) {
    tokio::time::sleep(Duration::from_secs(20)).await; // let the engine and UI start first
    loop {
        if auto_update_on() {
            let found: Result<Option<Update>, tauri_plugin_updater::Error> =
                async { app.updater()?.check().await }.await;
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
    TcpStream::connect_timeout(
        &"127.0.0.1:7878".parse().unwrap(),
        Duration::from_millis(300),
    )
    .is_ok()
}

fn io_err(e: impl ToString) -> std::io::Error {
    std::io::Error::other(e.to_string())
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
        std::fs::create_dir_all(&dest)?;
        let ok = Command::new("tar")
            .arg("-xzf")
            .arg(res.join("engine.tar.gz"))
            .arg("-C")
            .arg(&dest)
            .status()?;
        if !ok.success() {
            let _ = std::fs::remove_dir_all(&unpacked); // never leave a half-unpacked engine behind
            return Err(io_err("could not unpack the engine"));
        }
    }
    Ok(unpacked)
}

fn start_engine(dir: PathBuf) -> std::io::Result<Child> {
    let exe = dir.join(if cfg!(windows) {
        "kerf-engine.exe"
    } else {
        "kerf-engine"
    });
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt; // bundlers don't always keep the exec bit on resources
        let _ = std::fs::set_permissions(&exe, std::fs::Permissions::from_mode(0o755));
    }
    let mut cmd = Command::new(&exe);
    cmd.arg("serve").current_dir(&dir).env("KERF_STUDIO", "1"); // the engine tells the UI that Studio self-updates
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console flashing up
    }
    cmd.spawn()
}

fn main() {
    let child = Arc::new(Mutex::new(None));
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .manage(Engine(child.clone()))
        .manage(Staged(Mutex::new(None)))
        .setup(move |app| {
            tauri::async_runtime::spawn(update_loop(app.handle().clone()));
            if !engine_up() {
                let res = app.path().resource_dir().map_err(io_err)?;
                let data = app.path().app_local_data_dir().map_err(io_err)?;
                let version = app.package_info().version.to_string();
                // off the UI thread: the first Linux launch unpacks the engine while the splash is showing
                std::thread::spawn(move || {
                    match engine_dir(res, data, &version).and_then(start_engine) {
                        Ok(c) => *child.lock().unwrap() = Some(c),
                        Err(e) => eprintln!("kerf: could not start the engine: {e}"), // the splash shows the retry hint
                    }
                });
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("kerf: failed to start")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut c) = app.state::<Engine>().0.lock().unwrap().take() {
                    let _ = c.kill(); // only the engine we started; a separately started one keeps running
                }
                if let Some((update, bytes)) = app.state::<Staged>().0.lock().unwrap().take() {
                    let _ = update.install(bytes); // engine already stopped, so its files can be replaced
                }
            }
        });
}
