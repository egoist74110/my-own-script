use toolbox_desktop_lib::window_layout::{initial_size, is_reachable, Rect};

#[test]
fn large_screens_cap_at_1600_by_1000() {
    assert_eq!(initial_size(3000.0, 1700.0), (1600.0, 1000.0));
}

#[test]
fn typical_screens_use_80_and_85_percent() {
    // 1920x1055 work area: 80% = 1536, 85% = 896.75
    let (w, h) = initial_size(1920.0, 1055.0);
    assert_eq!(w, 1536.0);
    assert!((h - 896.75).abs() < 1e-9);
}

#[test]
fn raised_to_1280x800_when_screen_allows() {
    // 80% of 1440 = 1152 < 1280; 85% of 900 = 765 < 800
    assert_eq!(initial_size(1440.0, 900.0), (1280.0, 800.0));
}

#[test]
fn never_exceeds_a_small_work_area() {
    assert_eq!(initial_size(1100.0, 700.0), (1100.0, 700.0));
    let (w, h) = initial_size(1200.0, 780.0);
    assert!(w <= 1200.0 && h <= 780.0);
}

#[test]
fn reachable_when_title_bar_is_on_a_monitor() {
    let mon = [
        Rect {
            x: 0,
            y: 0,
            w: 2560,
            h: 1440,
        },
        Rect {
            x: 2560,
            y: 0,
            w: 1920,
            h: 1080,
        },
    ];
    assert!(is_reachable(
        Rect {
            x: 100,
            y: 100,
            w: 1280,
            h: 800
        },
        &mon
    ));
    assert!(is_reachable(
        Rect {
            x: 2700,
            y: 50,
            w: 1280,
            h: 800
        },
        &mon
    ));
}

#[test]
fn unreachable_when_monitor_was_unplugged_or_offscreen() {
    let mon = [Rect {
        x: 0,
        y: 0,
        w: 2560,
        h: 1440,
    }];
    assert!(!is_reachable(
        Rect {
            x: 3000,
            y: 100,
            w: 1280,
            h: 800
        },
        &mon
    ));
    assert!(!is_reachable(
        Rect {
            x: 100,
            y: 5000,
            w: 1280,
            h: 800
        },
        &mon
    ));
    assert!(!is_reachable(
        Rect {
            x: 0,
            y: 0,
            w: 100,
            h: 100
        },
        &[]
    ));
}
