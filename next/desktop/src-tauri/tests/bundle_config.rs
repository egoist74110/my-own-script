use std::path::{Component, Path, PathBuf};

fn normalize(path: &Path) -> PathBuf {
    let mut result = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                assert!(result.pop());
            }
            _ => result.push(component.as_os_str()),
        }
    }
    result
}

#[test]
fn bundle_overlay_maps_staging_resources_without_affecting_development() {
    let tauri_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let overlay: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(tauri_dir.join("tauri.bundle.conf.json")).unwrap(),
    )
    .unwrap();
    let default_text = std::fs::read_to_string(tauri_dir.join("tauri.conf.json")).unwrap();
    let default: serde_json::Value = serde_json::from_str(&default_text).unwrap();
    let resources = overlay["bundle"]["resources"].as_object().unwrap();
    assert_eq!(resources.len(), 1);
    let repo = normalize(&tauri_dir.join("../../.."));
    let key = "../../build/app-resources/backend";
    assert_eq!(resources[key], "backend");
    assert_eq!(
        normalize(&tauri_dir.join(key)),
        repo.join("next/build/app-resources/backend")
    );
    assert!(!default_text.contains("app-resources"));
    assert_eq!(default["version"], "1.0.0");
    assert_eq!(default["productName"], "TOOLBOX");
    assert_eq!(default["identifier"], "dev.toolbox.next");
    // Measured by verify_app.sh: highest Mach-O minos in the bundle (playwright's bundled node).
    assert_eq!(overlay["bundle"]["macOS"]["minimumSystemVersion"], "13.5");
    assert!(default
        .pointer("/bundle/macOS/minimumSystemVersion")
        .is_none());
}

#[test]
fn default_config_excludes_updater_and_example_overlay_is_valid() {
    let tauri_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let default_text = std::fs::read_to_string(tauri_dir.join("tauri.conf.json")).unwrap();
    let default: serde_json::Value = serde_json::from_str(&default_text).unwrap();
    assert!(!default_text.contains("updater"));
    assert!(default.pointer("/plugins/updater").is_none());
    assert!(default.pointer("/bundle/createUpdaterArtifacts").is_none());

    let bundle_overlay: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(tauri_dir.join("tauri.bundle.conf.json")).unwrap(),
    )
    .unwrap();
    assert!(bundle_overlay
        .pointer("/bundle/createUpdaterArtifacts")
        .is_none());
    assert!(bundle_overlay.pointer("/plugins/updater").is_none());

    let example: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(tauri_dir.join("tauri.updater.conf.example.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(example["bundle"]["createUpdaterArtifacts"], true);
    assert_eq!(
        example["plugins"]["updater"]["pubkey"],
        "REPLACE_WITH_MINISIGN_PUBLIC_KEY"
    );
    assert_eq!(
        example["plugins"]["updater"]["endpoints"],
        serde_json::json!(["https://github.com/OWNER/REPO/releases/latest/download/latest.json"])
    );
}

#[test]
fn capabilities_main_json_adds_only_five_updater_commands() {
    let tauri_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let cap: serde_json::Value = serde_json::from_str(
        &std::fs::read_to_string(tauri_dir.join("capabilities/main.json")).unwrap(),
    )
    .unwrap();
    let perms = cap["permissions"].as_array().unwrap();
    let string_perms: Vec<&str> = perms.iter().filter_map(|p| p.as_str()).collect();
    assert_eq!(
        string_perms,
        vec![
            "allow-backend-connection",
            "allow-backend-status",
            "allow-update-status",
            "allow-update-check",
            "allow-update-install",
            "allow-update-cancel",
            "allow-update-restart",
            "core:event:allow-listen",
            "core:event:allow-unlisten",
            "core:window:allow-start-dragging",
            "core:window:allow-toggle-maximize",
        ]
    );
    assert_eq!(perms.len(), string_perms.len() + 1);
    assert_eq!(perms.last().unwrap()["identifier"], "opener:allow-open-url");
}
