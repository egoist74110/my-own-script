fn main() {
    // Only the shell's own commands are exposed to the page, each behind an
    // explicit `allow-*` permission (see capabilities/main.json).
    let manifest = tauri_build::AppManifest::new().commands(&[
        "backend_connection",
        "backend_status",
        "update_status",
        "update_check",
        "update_install",
        "update_cancel",
        "update_restart",
    ]);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(manifest))
        .expect("failed to run tauri-build");
}
