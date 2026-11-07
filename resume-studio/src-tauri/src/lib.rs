use base64::{engine::general_purpose::STANDARD, Engine};
use serde_json::Value;
use std::{fs, io::{Read, Write}, path::{Path, PathBuf}, process::{Command, Stdio}, sync::Mutex, time::{Duration, Instant, SystemTime, UNIX_EPOCH}};
use tauri::Manager;

const MAX_FILE: u64 = 12_000_000;
struct StorageLock(Mutex<()>);

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let parent = path.parent().ok_or("Choose a valid destination folder.")?;
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    let temporary = parent.join(format!(".resume-studio-{}-{nonce}.tmp", std::process::id()));
    let result = (|| {
        let mut file = fs::OpenOptions::new().write(true).create_new(true).open(&temporary).map_err(|e| e.to_string())?;
        file.write_all(bytes).map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
        drop(file);
        fs::rename(&temporary, path).map_err(|e| format!("Could not save the file. Close it in Word if it is open, then try again. {e}"))
    })();
    if result.is_err() { let _ = fs::remove_file(&temporary); }
    result
}

fn workspace_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path().app_data_dir().map(|p| p.join("workspace.json")).map_err(|e| e.to_string())
}

#[tauri::command]
fn load_workspace(app: tauri::AppHandle) -> Result<Value, String> {
    let path = workspace_path(&app)?;
    match fs::read(&path) {
        Ok(bytes) => serde_json::from_slice(&bytes).map_err(|e| format!("The saved workspace could not be read: {e}. A backup is stored beside {}.", path.display())),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Value::Null),
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
fn save_workspace(app: tauri::AppHandle, workspace: Value, lock: tauri::State<StorageLock>) -> Result<(), String> {
    let _guard = lock.0.lock().map_err(|e| e.to_string())?;
    if !workspace["documents"].is_array() || !workspace["revisions"].is_array() { return Err("Invalid workspace data.".into()); }
    let bytes = serde_json::to_vec_pretty(&workspace).map_err(|e| e.to_string())?;
    if bytes.len() as u64 > MAX_FILE { return Err("The workspace exceeds the 12 MB storage limit. Export a backup before removing old revisions.".into()); }
    let path = workspace_path(&app)?;
    if path.exists() {
        let previous = fs::read(&path).map_err(|e| e.to_string())?;
        atomic_write(&path.with_extension("backup.json"), &previous)?;
    }
    atomic_write(&path, &bytes)
}

#[tauri::command]
fn read_source(path: String) -> Result<String, String> {
    let path = Path::new(&path);
    let extension = path.extension().and_then(|s| s.to_str()).unwrap_or("").to_lowercase();
    if !["yaml", "yml", "toml"].contains(&extension.as_str()) { return Err("Choose a YAML or TOML file.".into()); }
    if fs::metadata(path).map_err(|e| e.to_string())?.len() > 2_000_000 { return Err("Choose a file smaller than 2 MB.".into()); }
    fs::read_to_string(path).map_err(|e| format!("Could not read the file as UTF-8: {e}"))
}

#[tauri::command]
fn write_export(path: String, content: String, binary: bool) -> Result<(), String> {
    let path = Path::new(&path);
    let extension = path.extension().and_then(|s| s.to_str()).unwrap_or("").to_lowercase();
    if !(if binary { extension == "docx" } else { ["yaml", "yml", "toml", "json", "log"].contains(&extension.as_str()) }) {
        return Err("Use the file extension shown in the save dialog.".into());
    }
    let bytes = if binary { STANDARD.decode(content).map_err(|e| e.to_string())? } else { content.into_bytes() };
    if bytes.len() as u64 > MAX_FILE { return Err("The export exceeds the 12 MB size limit.".into()); }
    atomic_write(path, &bytes)
}

fn call_engine(request: Value) -> Result<Value, String> {
    let input = serde_json::to_vec(&request).map_err(|e| e.to_string())?;
    if input.len() > 6_000_000 { return Err("The source files are too large.".into()); }
    let mut command = if cfg!(debug_assertions) {
        let mut cmd = Command::new(std::env::var("RESUME_STUDIO_PYTHON").unwrap_or_else(|_| "python".into()));
        cmd.arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("../python/engine.py"));
        cmd
    } else {
        let executable = std::env::current_exe().map_err(|e| e.to_string())?;
        Command::new(executable.parent().ok_or("Application folder is unavailable.")?.join(if cfg!(windows) { "resume-engine.exe" } else { "resume-engine" }))
    };
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn()
        .map_err(|e| format!("Could not start the Python engine. In development, install python/requirements.txt. {e}"))?;
    let mut stdout = child.stdout.take().ok_or("Missing engine output.")?;
    let mut stderr = child.stderr.take().ok_or("Missing engine error output.")?;
    let output_thread = std::thread::spawn(move || { let mut buf = Vec::new(); stdout.read_to_end(&mut buf).map(|_| buf) });
    let error_thread = std::thread::spawn(move || { let mut buf = Vec::new(); stderr.read_to_end(&mut buf).map(|_| buf) });
    let mut stdin = child.stdin.take().ok_or("Missing engine input.")?;
    let write_result = stdin.write_all(&input);
    drop(stdin);
    if write_result.is_err() { let _ = child.kill(); }
    let start = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) if start.elapsed() < Duration::from_secs(60) => std::thread::sleep(Duration::from_millis(25)),
            _ => {
                let _ = child.kill(); let _ = child.wait();
                let _ = output_thread.join(); let _ = error_thread.join();
                return Err("Generation stopped after 60 seconds. Check the source files and try again.".into());
            }
        }
    }
    let output = output_thread.join().map_err(|_| "Could not read engine output.")?.map_err(|e| e.to_string())?;
    let errors = error_thread.join().map_err(|_| "Could not read engine diagnostics.")?.map_err(|e| e.to_string())?;
    serde_json::from_slice(&output).map_err(|e| format!("The engine did not return a valid result: {e}\n{}", String::from_utf8_lossy(&errors)))
}

#[tauri::command]
async fn run_engine(request: Value) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || call_engine(request)).await.map_err(|e| e.to_string())?
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(StorageLock(Mutex::new(())))
        .invoke_handler(tauri::generate_handler![run_engine, load_workspace, save_workspace, read_source, write_export])
        .run(tauri::generate_context!())
        .expect("Could not start Resume Studio");
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn save_replaces_an_existing_file() {
        let folder = std::env::temp_dir().join(format!("resume-studio-test-{}", std::process::id()));
        let path = folder.join("workspace.json");
        atomic_write(&path, b"first").unwrap();
        atomic_write(&path, b"second").unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"second");
        fs::remove_file(path).unwrap(); fs::remove_dir(folder).unwrap();
    }
}
