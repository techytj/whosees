//! JNI entry points for io.github.techytj.wiretrace.Engine (Kotlin object with @JvmStatic externals).

use crate::engine::{AppInfo, Config, Engine};
use crate::sock::Proto;
use jni::objects::{GlobalRef, JClass, JString, JValue};
use jni::sys::{jint, jstring};
use jni::{JNIEnv, JavaVM};
use std::sync::{Arc, Mutex, OnceLock};

static ENGINE: Mutex<Option<Engine>> = Mutex::new(None);
static VM: OnceLock<(JavaVM, GlobalRef)> = OnceLock::new();

fn jstr(env: &mut JNIEnv, s: &JString) -> String { env.get_string(s).map(|s| s.into()).unwrap_or_default() }
fn out(env: &mut JNIEnv, s: &str) -> jstring { env.new_string(s).map(|s| s.into_raw()).unwrap_or(std::ptr::null_mut()) }

/// Calls Engine.appFor(proto, srcIp, srcPort, dstIp, dstPort): String (JSON AppInfo) on the Kotlin side.
fn owner_lookup(proto: Proto, local: std::net::SocketAddr, remote: std::net::SocketAddr) -> AppInfo {
    let fallback = AppInfo { id: "unknown".into(), name: "Unknown app".into(), icon: None, system: false, uid: -1, perms: vec![] };
    let Some((vm, cls)) = VM.get() else { return fallback };
    let Ok(mut env) = vm.attach_current_thread_permanently() else { return fallback };
    let (Ok(s), Ok(d)) = (env.new_string(local.ip().to_string()), env.new_string(remote.ip().to_string())) else { return fallback };
    let r = env.call_static_method(<&JClass>::from(cls.as_obj()), "appFor", "(ILjava/lang/String;ILjava/lang/String;I)Ljava/lang/String;",
        &[JValue::Int(if proto == Proto::Tcp { 6 } else { 17 }), JValue::Object(&s), JValue::Int(local.port() as i32),
          JValue::Object(&d), JValue::Int(remote.port() as i32)]);
    let Ok(obj) = r.and_then(|v| v.l()) else { let _ = env.exception_clear(); return fallback };
    let js: String = env.get_string(&JString::from(obj)).map(|s| s.into()).unwrap_or_default();
    serde_json::from_str::<serde_json::Value>(&js).map(|v| AppInfo {
        id: v["id"].as_str().unwrap_or("unknown").into(), name: v["name"].as_str().unwrap_or("Unknown app").into(),
        icon: v["icon"].as_str().map(String::from), system: v["system"].as_bool().unwrap_or(false), uid: v["uid"].as_i64().unwrap_or(-1),
        perms: v["perms"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default(),
    }).unwrap_or(fallback)
}

#[no_mangle]
pub extern "system" fn Java_io_github_techytj_wiretrace_Engine_nativeStart(mut env: JNIEnv, cls: JClass, fd: jint, cfg: JString) -> jint {
    if VM.get().is_none() {
        if let (Ok(vm), Ok(g)) = (env.get_java_vm(), env.new_global_ref(&cls)) { let _ = VM.set((vm, g)); }
    }
    let cfg: Config = serde_json::from_str(&jstr(&mut env, &cfg)).unwrap_or_default();
    let mut guard = ENGINE.lock().unwrap();
    if let Some(mut e) = guard.take() { e.stop(); }
    match Engine::start(fd, cfg, Arc::new(owner_lookup)) { Ok(e) => { *guard = Some(e); 0 } Err(_) => -1 }
}

#[no_mangle]
pub extern "system" fn Java_io_github_techytj_wiretrace_Engine_nativeStop(_env: JNIEnv, _cls: JClass) {
    if let Some(mut e) = ENGINE.lock().unwrap().take() { e.stop(); }
}

#[no_mangle]
pub extern "system" fn Java_io_github_techytj_wiretrace_Engine_nativePoll(mut env: JNIEnv, _cls: JClass) -> jstring {
    let s = ENGINE.lock().unwrap().as_ref().map(|e| e.poll()).unwrap_or_else(|| "[]".into());
    out(&mut env, &s)
}

#[no_mangle]
pub extern "system" fn Java_io_github_techytj_wiretrace_Engine_nativeCommand(mut env: JNIEnv, _cls: JClass, json: JString) {
    let j = jstr(&mut env, &json);
    if let Some(e) = ENGINE.lock().unwrap().as_ref() { e.command(&j); }
}

#[no_mangle]
pub extern "system" fn Java_io_github_techytj_wiretrace_Engine_nativeFindCity(mut env: JNIEnv, _cls: JClass, geo: JString, q: JString) -> jstring {
    let (g, q) = (jstr(&mut env, &geo), jstr(&mut env, &q));
    let hits = crate::geo::Geo::open(std::path::Path::new(&g)).map(|g| g.find_cities(&q, 12)).unwrap_or_default();
    let s = serde_json::to_string(&hits).unwrap_or_else(|_| "[]".into());
    out(&mut env, &s)
}
