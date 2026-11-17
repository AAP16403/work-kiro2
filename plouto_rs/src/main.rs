use std::io::Write;
use std::path::PathBuf;
use std::process::ExitCode;

use plouto_rs::app::{run_desktop_game, AppConfig};
use plouto_rs::sim::replay::{load_recording, replay_and_verify};

fn write_crash_report(message: &str) {
    let path = plouto_rs::assets::resolve_data_file("crash.log");
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
    {
        let _ = writeln!(
            file,
            "{} PLOUTO {} (simulation rules {})\n{message}\n",
            chrono::Utc::now().to_rfc3339(),
            env!("CARGO_PKG_VERSION"),
            plouto_rs::sim::replay::SIMULATION_RULES_VERSION
        );
        eprintln!("Crash details saved to {}", path.display());
    }
}

fn print_usage() {
    println!("PLOUTO — Stellar Survival");
    println!("Usage:");
    println!("  plouto                  Launch interactive desktop game");
    println!("  plouto --record <file>  Record deterministic run inputs to JSON");
    println!("  plouto --replay <file>  Verify deterministic replay hash from JSON");
    println!("  plouto --help           Show this message");
}

fn main() -> ExitCode {
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        write_crash_report(&format!(
            "{info}\n{}",
            std::backtrace::Backtrace::force_capture()
        ));
        default_hook(info);
    }));
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut record_path: Option<PathBuf> = None;
    let mut replay_path: Option<PathBuf> = None;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--help" | "-h" => {
                print_usage();
                return ExitCode::SUCCESS;
            }
            "--record" => {
                if let Some(val) = args.get(i + 1) {
                    record_path = Some(PathBuf::from(val));
                    i += 2;
                    continue;
                }
                eprintln!("--record requires a file path");
                return ExitCode::FAILURE;
            }
            "--replay" => {
                if let Some(val) = args.get(i + 1) {
                    replay_path = Some(PathBuf::from(val));
                    i += 2;
                    continue;
                }
                eprintln!("--replay requires a file path");
                return ExitCode::FAILURE;
            }
            other => {
                eprintln!("Unknown option: {other}");
                print_usage();
                return ExitCode::FAILURE;
            }
        }
    }

    if let Some(path) = replay_path {
        let rec = match load_recording(&path) {
            Ok(r) => r,
            Err(err) => {
                eprintln!("Replay load failed: {err}");
                return ExitCode::FAILURE;
            }
        };
        let res = replay_and_verify(&rec);
        if let Some(error) = &res.error {
            eprintln!("Replay verification failed: {error}");
            return ExitCode::FAILURE;
        }
        println!(
            "Replay frames={} wave={} score={} expected={} actual={} match={}",
            res.frames_run, res.final_wave, res.final_score, res.expected_hash, res.actual_hash, res.matches
        );
        if let Some(frame) = res.first_mismatch_frame {
            eprintln!("First replay divergence at frame {frame}.");
        }
        return if res.matches {
            ExitCode::SUCCESS
        } else {
            eprintln!("Replay hash mismatch!");
            ExitCode::FAILURE
        };
    }

    if let Err(err) = run_desktop_game(AppConfig { record_path }) {
        write_crash_report(&err);
        eprintln!("Fatal application error: {err}");
        return ExitCode::FAILURE;
    }
    ExitCode::SUCCESS
}
