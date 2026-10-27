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
    assert_eq!(resources.len(), 2);
    let repo = normalize(&tauri_dir.join("../../.."));
    for name in ["backend", "mcp"] {
        let key = format!("../../build/app-resources/{name}");
        assert_eq!(resources[&key], name);
        assert_eq!(
            normalize(&tauri_dir.join(&key)),
            repo.join("next/build/app-resources").join(name)
        );
    }
    assert!(!default_text.contains("app-resources"));
    assert_eq!(default["version"], "1.0.0");
    assert_eq!(default["productName"], "TOOLBOX");
    assert_eq!(default["identifier"], "dev.toolbox.next");
    assert!(overlay
        .pointer("/bundle/macOS/minimumSystemVersion")
        .is_none());
    assert!(default
        .pointer("/bundle/macOS/minimumSystemVersion")
        .is_none());
}
