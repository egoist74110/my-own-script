use std::{fs, path::Path};

use toolbox_desktop_lib::backend::BackendCommand;

#[test]
fn packaged_runtime_works_without_repo_root() {
    let temp = tempfile::tempdir().unwrap();
    let contents = temp.path().join("TOOLBOX.app/Contents");
    let macos = contents.join("MacOS");
    let backend = contents.join("Resources/backend");
    fs::create_dir_all(&macos).unwrap();
    fs::create_dir_all(backend.join("bin")).unwrap();
    let python = backend.join("bin/python3.14");
    fs::write(&python, "").unwrap();
    let repo = temp.path().join("missing-repo");
    assert!(!repo.exists());

    let command = BackendCommand::packaged(&macos.join("toolbox-desktop"), &repo, None).unwrap();
    assert_eq!(Path::new(&command.program), python);
    assert_eq!(command.args, ["-m", "toolbox_backend"]);
    assert!(!command.args.iter().any(|arg| arg == "--dev"));
    assert_eq!(command.cwd.as_deref(), Some(backend.as_path()));
    assert_eq!(
        command.env,
        vec![
            ("PYTHONDONTWRITEBYTECODE".into(), "1".into()),
            ("PYTHONNOUSERSITE".into(), "1".into()),
        ]
    );
}

#[test]
fn override_takes_priority_over_packaged_runtime_and_rejects_unbalanced_quotes() {
    let temp = tempfile::tempdir().unwrap();
    let contents = temp.path().join("Contents");
    fs::create_dir_all(contents.join("MacOS")).unwrap();
    fs::create_dir_all(contents.join("Resources/backend/bin")).unwrap();
    fs::write(contents.join("Resources/backend/bin/python3.14"), "").unwrap();
    let executable = contents.join("MacOS/toolbox-desktop");
    let backend = temp.path().join("next/backend");
    fs::create_dir_all(&backend).unwrap();
    let command =
        BackendCommand::packaged(&executable, temp.path(), Some("/bin/echo 'two words' x"))
            .unwrap();
    assert_eq!(command.program, "/bin/echo");
    assert_eq!(command.args, ["two words", "x"]);
    assert_eq!(command.cwd.as_deref(), Some(backend.as_path()));
    assert!(command.env.is_empty());
    assert_eq!(
        BackendCommand::packaged(&executable, temp.path(), Some("'unbalanced")).unwrap_err(),
        "TOOLBOX_BACKEND_CMD has unbalanced quotes"
    );
    let blank = BackendCommand::packaged(&executable, temp.path(), Some("   ")).unwrap();
    assert_eq!(blank.args, ["-m", "toolbox_backend"]);
}

#[test]
fn missing_resources_or_python_falls_back_to_unchanged_dev_command() {
    let temp = tempfile::tempdir().unwrap();
    let contents = temp.path().join("Contents");
    fs::create_dir_all(contents.join("MacOS")).unwrap();
    let executable = contents.join("MacOS/toolbox-desktop");
    for create_backend_dir in [false, true] {
        if create_backend_dir {
            fs::create_dir_all(contents.join("Resources/backend/bin")).unwrap();
            fs::create_dir_all(temp.path().join("next/backend")).unwrap();
        }
        for override_cmd in [None, Some("   ")] {
            let command = BackendCommand::packaged(&executable, temp.path(), override_cmd).unwrap();
            assert_eq!(
                Path::new(&command.program),
                temp.path().join("next/backend/.venv/bin/python")
            );
            assert_eq!(command.args, ["-m", "toolbox_backend", "--dev"]);
            assert!(command.env.is_empty());
            let expected_cwd = create_backend_dir.then(|| temp.path().join("next/backend"));
            assert_eq!(command.cwd, expected_cwd);
        }
    }
}
