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

struct Engine(Arc<Mutex<Option<Child>>>);

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
    cmd.arg("serve").current_dir(&dir);
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
        .manage(Engine(child.clone()))
        .setup(move |app| {
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
            }
        });
}
