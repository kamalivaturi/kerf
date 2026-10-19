// Kerf Studio: native shell around the Kerf engine. Starts the bundled engine (unless one is already
// running, e.g. for the Premiere panel), shows the splash until it answers, then the app UI at /app/.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::{net::TcpStream, process::{Child, Command}, sync::Mutex, time::Duration};
use tauri::{Manager, RunEvent};

struct Engine(Mutex<Option<Child>>);

fn engine_up() -> bool {
    TcpStream::connect_timeout(&"127.0.0.1:7878".parse().unwrap(), Duration::from_millis(300)).is_ok()
}

fn start_engine(app: &tauri::App) -> std::io::Result<Child> {
    let dir = app.path().resource_dir().map_err(|e| std::io::Error::other(e.to_string()))?.join("engine");
    let exe = dir.join(if cfg!(windows) { "kerf-engine.exe" } else { "kerf-engine" });
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
    tauri::Builder::default()
        .manage(Engine(Mutex::new(None)))
        .setup(|app| {
            if !engine_up() {
                match start_engine(app) {
                    Ok(child) => *app.state::<Engine>().0.lock().unwrap() = Some(child),
                    Err(e) => eprintln!("kerf: could not start the engine: {e}"), // the splash shows the retry hint
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("kerf: failed to start")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Engine>().0.lock().unwrap().take() {
                    let _ = child.kill(); // only the engine we started; a separately started one keeps running
                }
            }
        });
}
