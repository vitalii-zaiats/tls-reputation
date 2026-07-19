#!/usr/bin/env python3
"""Ground-truth TLS-fingerprint catalog.

Runs a grid of (HTTP client × runtime image) in Docker. Each cell makes one
HTTPS request to tls.peet.ws — a public fingerprint reflector that computes
JA3/JA4 the same way this project's own engine does (verified: the same
container yields the same JA4 from tls.peet.ws and from tls-reputation's
collector) — and reports the JA4 that client-in-that-environment produces. So
an anonymous JA4 in the corpus becomes a name: "Python requests on Alpine,"
"Node undici on Debian."

Cells are language-typed: a client's `lang` must match its environment's, so
Python clients run on Python images and Node clients on Node images. The
program is fed to the interpreter/compiler over stdin (via a temp file), so
there is no shell-quoting to get wrong.

Six languages, and the axis that moves a fingerprint differs by language:
    python  ja4_b tracks the OpenSSL build (base image), ja4_c the library
    node    bundles its own OpenSSL, so base is irrelevant; Node major sets it
    go      pure-Go crypto/tls; base irrelevant, Go version + CGO set it
    java    pure-Java JSSE; base irrelevant, the JDK sets it, libraries collapse
    dotnet  uses the OS OpenSSL, so base image matters (like python)
    rust    depends on the TLS backend: native-tls = OpenSSL (base matters),
            rustls = pure Rust (base irrelevant)

Usage:
    python matrix.py                       # the starter grid (all languages)
    python matrix.py --lang rust           # one language
    python matrix.py --lang java --lang go # several
    python matrix.py --full                # every client on every image (slow)
    python matrix.py --jobs 8
Writes catalog.md and catalog.json next to this file.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import subprocess
import sys

URL = "https://tls.peet.ws/api/all"
HOST = "tls.peet.ws"

# Each client prints "ja4<TAB>ja3_hash" and nothing else on success.
_PY = 't=%s["tls"]; import sys; sys.stdout.write(t["ja4"]+chr(9)+t["ja3_hash"])'
_JS_TAIL = "const t=d.tls;process.stdout.write(t.ja4+String.fromCharCode(9)+t.ja3_hash)"
_JS_ERR = ".catch(function(e){console.error(String(e));process.exit(1)})"

# Java has no standard JSON parser, so pull the two values out by hand. The
# search token is `key":`, which matches `"ja4":` but not `"ja4_r":` (the char
# after ja4 there is `_`, not a quote), so a naive scan is safe. chars 9/34/58
# are TAB / " / : — spelled by code to avoid a nest of escaped quotes.
_JX = (
    'static String x(String s,String k){int i=s.indexOf(k+(char)34+(char)58);'
    "int p=s.indexOf((char)34,i+k.length()+2)+1;"
    "return s.substring(p,s.indexOf((char)34,p));}"
)
_J_TAIL = 'System.out.print(x(b,"ja4")+(char)9+x(b,"ja3_hash"));}' + _JX + "}"

# Rust: fetch to a String, parse with serde_json, print the two fields. Only the
# fetch line differs between clients (reqwest vs ureq), so the rest is shared.
_RS_TAIL = (
    'let v:serde_json::Value=serde_json::from_str(&b).unwrap();let t=&v["tls"];'
    'print!("{}\\t{}",t["ja4"].as_str().unwrap(),t["ja3_hash"].as_str().unwrap());}'
)

CLIENTS: dict[str, dict] = {
    # ── Python ──
    "py urllib (stdlib)": {"lang": "python", "pkg": None,
        "code": f'import urllib.request,json; d=json.load(urllib.request.urlopen("{URL}",timeout=25)); ' + _PY % "d"},
    "py http.client (stdlib)": {"lang": "python", "pkg": None,
        "code": f'import http.client,json; c=http.client.HTTPSConnection("{HOST}",timeout=25); '
                'c.request("GET","/api/all"); d=json.load(c.getresponse()); ' + _PY % "d"},
    "py requests": {"lang": "python", "pkg": "requests",
        "code": f'import requests; d=requests.get("{URL}",timeout=25).json(); ' + _PY % "d"},
    "py urllib3": {"lang": "python", "pkg": "urllib3",
        "code": f'import urllib3,json; d=json.loads(urllib3.PoolManager().request("GET","{URL}").data); ' + _PY % "d"},
    "py httpx": {"lang": "python", "pkg": "httpx",
        "code": f'import httpx; d=httpx.get("{URL}",timeout=25).json(); ' + _PY % "d"},
    "py aiohttp": {"lang": "python", "pkg": "aiohttp",
        "code": "import aiohttp,asyncio\n"
                "async def m():\n"
                "    async with aiohttp.ClientSession() as s:\n"
                f'        async with s.get("{URL}") as r:\n'
                "            d=await r.json()\n"
                "            " + _PY % "d" + "\n"
                "asyncio.run(m())"},

    # ── Node.js ──  the runtime bundles its own OpenSSL, so the JA4 tracks the
    # Node major, not the base OS.
    "node https (stdlib)": {"lang": "node", "pkg": None,
        "code": f"const https=require('https');https.get('{URL}',function(r){{let d='';"
                "r.on('data',function(c){d+=c});r.on('end',function(){const o=JSON.parse(d);"
                f"const t=o.tls;process.stdout.write(t.ja4+String.fromCharCode(9)+t.ja3_hash)}})}})"
                ".on('error',function(e){console.error(String(e));process.exit(1)})"},
    "node fetch (global)": {"lang": "node", "pkg": None,
        "code": f"fetch('{URL}').then(function(r){{return r.json()}}).then(function(d){{{_JS_TAIL}}})" + _JS_ERR},
    "node undici": {"lang": "node", "pkg": "undici",
        "code": f"const {{request}}=require('undici');request('{URL}').then(async function(x){{"
                f"const d=await x.body.json();{_JS_TAIL}}})" + _JS_ERR},
    "node axios": {"lang": "node", "pkg": "axios",
        "code": f"const axios=require('axios');axios.get('{URL}').then(function(r){{const d=r.data;{_JS_TAIL}}})" + _JS_ERR},
    "node node-fetch": {"lang": "node", "pkg": "node-fetch@2",
        "code": f"const fetch=require('node-fetch');fetch('{URL}').then(function(r){{return r.json()}})"
                f".then(function(d){{{_JS_TAIL}}})" + _JS_ERR},
    "node got": {"lang": "node", "pkg": "got@11",
        "code": f"const got=require('got');got('{URL}').json().then(function(d){{{_JS_TAIL}}})" + _JS_ERR},

    # ── Go ──  crypto/tls is pure Go, no OpenSSL, so the JA4 tracks the Go
    # version alone and is identical across every base image (a statically
    # linked binary carries its whole TLS stack).
    "go net/http (stdlib)": {"lang": "go", "pkg": None, "code": r'''package main
import ("encoding/json";"io";"net/http";"os")
type R struct{ TLS struct{ JA4 string `json:"ja4"`; JA3 string `json:"ja3_hash"` } `json:"tls"` }
func main(){
	resp,err:=http.Get("''' + URL + r'''")
	if err!=nil{os.Stderr.WriteString(err.Error());os.Exit(1)}
	b,_:=io.ReadAll(resp.Body)
	var d R
	json.Unmarshal(b,&d)
	os.Stdout.Write([]byte(d.TLS.JA4+"\t"+d.TLS.JA3))
}'''},

    # ── Java ──  every client here hands the TLS handshake to the JDK's own
    # JSSE (SunJSSE), which is pure Java. So the JA4 tracks the JDK, is the same
    # on Debian and Alpine, and OkHttp / Apache collapse onto java.net.http.
    # OkHttp and Apache need jars on the classpath; `setup` fetches them and
    # `cp` puts them on the single-file `java Src.java` launch.
    "java java.net.http (stdlib)": {"lang": "java", "pkg": None,
        "code": ('import java.net.http.*;import java.net.URI;public class M{'
                 'public static void main(String[] a)throws Exception{'
                 'HttpClient c=HttpClient.newHttpClient();'
                 'String b=c.send(HttpRequest.newBuilder(URI.create("URL")).build(),'
                 'HttpResponse.BodyHandlers.ofString()).body();' + _J_TAIL).replace("URL", URL)},
    "java okhttp": {"lang": "java",
        "pkg": None,
        "cp": '-cp "/jars/*"',
        "setup": "mkdir -p /jars && "
                 "( command -v curl >/dev/null 2>&1 || "
                 "( (apt-get update -qq && apt-get install -y -qq curl) >/dev/null 2>&1 || apk add --no-cache curl >/dev/null 2>&1 ) ) && "
                 "curl -sL -o /jars/okhttp.jar https://repo1.maven.org/maven2/com/squareup/okhttp3/okhttp/4.12.0/okhttp-4.12.0.jar && "
                 "curl -sL -o /jars/okio.jar https://repo1.maven.org/maven2/com/squareup/okio/okio-jvm/3.6.0/okio-jvm-3.6.0.jar && "
                 "curl -sL -o /jars/kotlin.jar https://repo1.maven.org/maven2/org/jetbrains/kotlin/kotlin-stdlib/1.9.10/kotlin-stdlib-1.9.10.jar",
        "code": ('import okhttp3.*;public class M{'
                 'public static void main(String[] a)throws Exception{'
                 'OkHttpClient c=new OkHttpClient();'
                 'String b=c.newCall(new Request.Builder().url("URL").build()).execute().body().string();'
                 + _J_TAIL).replace("URL", URL)},
    "java apache httpclient5": {"lang": "java",
        "pkg": None,
        "cp": '-cp "/jars/*"',
        "setup": "mkdir -p /jars && "
                 "( command -v curl >/dev/null 2>&1 || "
                 "( (apt-get update -qq && apt-get install -y -qq curl) >/dev/null 2>&1 || apk add --no-cache curl >/dev/null 2>&1 ) ) && "
                 "curl -sL -o /jars/hc5.jar https://repo1.maven.org/maven2/org/apache/httpcomponents/client5/httpclient5/5.3.1/httpclient5-5.3.1.jar && "
                 "curl -sL -o /jars/hcore5.jar https://repo1.maven.org/maven2/org/apache/httpcomponents/core5/httpcore5/5.2.4/httpcore5-5.2.4.jar && "
                 "curl -sL -o /jars/hcore5h2.jar https://repo1.maven.org/maven2/org/apache/httpcomponents/core5/httpcore5-h2/5.2.4/httpcore5-h2-5.2.4.jar && "
                 "curl -sL -o /jars/slf4j.jar https://repo1.maven.org/maven2/org/slf4j/slf4j-api/2.0.13/slf4j-api-2.0.13.jar && "
                 "curl -sL -o /jars/slf4jn.jar https://repo1.maven.org/maven2/org/slf4j/slf4j-nop/2.0.13/slf4j-nop-2.0.13.jar",
        "code": ('import org.apache.hc.client5.http.classic.methods.HttpGet;'
                 'import org.apache.hc.client5.http.impl.classic.*;'
                 'import org.apache.hc.core5.http.io.entity.EntityUtils;public class M{'
                 'public static void main(String[] a)throws Exception{'
                 'CloseableHttpClient c=HttpClients.createDefault();'
                 'String b=c.execute(new HttpGet("URL"),r->EntityUtils.toString(r.getEntity()));'
                 + _J_TAIL).replace("URL", URL)},

    # ── C# / .NET ──  HttpClient (SocketsHttpHandler) drives the handshake
    # through libSystem.Security.Cryptography.Native.OpenSsl — the OS OpenSSL.
    # So, like Python, the JA4 shifts with the base image's OpenSSL, and the
    # .NET major sets the client's own preferences on top.
    "dotnet HttpClient (stdlib)": {"lang": "dotnet", "pkg": None,
        "code": ('using System.Text.Json;'
                 'var http=new System.Net.Http.HttpClient();'
                 'var s=await http.GetStringAsync("URL");'
                 'using var doc=JsonDocument.Parse(s);var t=doc.RootElement.GetProperty("tls");'
                 'System.Console.Write(t.GetProperty("ja4").GetString()+"\\t"+t.GetProperty("ja3_hash").GetString());'
                 ).replace("URL", URL)},

    # ── Rust ──  the finding is the TLS backend, not the base image. reqwest's
    # default `native-tls` is OpenSSL on Linux (base matters); its `rustls-tls`
    # feature is pure Rust (base irrelevant). ureq is rustls-only. `pkg` is the
    # exact reqwest/ureq dependency line dropped into Cargo.toml.
    "rust reqwest (native-tls)": {"lang": "rust",
        "pkg": 'reqwest = { version = "0.12", features = ["blocking"] }',
        "code": ('fn main(){let b=reqwest::blocking::get("URL").unwrap().text().unwrap();'
                 + _RS_TAIL).replace("URL", URL)},
    "rust reqwest (rustls)": {"lang": "rust",
        "pkg": 'reqwest = { version = "0.12", default-features = false, features = ["blocking", "rustls-tls"] }',
        "code": ('fn main(){let b=reqwest::blocking::get("URL").unwrap().text().unwrap();'
                 + _RS_TAIL).replace("URL", URL)},
    "rust ureq (rustls)": {"lang": "rust",
        "pkg": 'ureq = "2"',
        "code": ('fn main(){let b=ureq::get("URL").call().unwrap().into_string().unwrap();'
                 + _RS_TAIL).replace("URL", URL)},
}

# Each environment: the language it provides, an optional bootstrap to install
# OS packages, env vars (exported once, so they reach both install and run), how
# to install a package, and how to run the program. `{pkg}` in install and
# `{cp}` in run are substituted per client.
ENVIRONMENTS: dict[str, dict] = {
    "python:3.9-slim": {"lang": "python", "install": "pip install -q {pkg}", "prog": "/p.py", "run": "python /p.py"},
    "python:3.11-slim": {"lang": "python", "install": "pip install -q {pkg}", "prog": "/p.py", "run": "python /p.py"},
    "python:3.13-slim": {"lang": "python", "install": "pip install -q {pkg}", "prog": "/p.py", "run": "python /p.py"},
    "python:3.11-alpine": {"lang": "python", "install": "pip install -q {pkg}", "prog": "/p.py", "run": "python /p.py"},
    "ghcr.io/astral-sh/uv:python3.12-bookworm-slim": {"lang": "python",
        "install": "uv pip install --system -q {pkg}", "prog": "/p.py", "run": "python /p.py"},
    "amazonlinux:2023": {"lang": "python", "bootstrap": "dnf install -y -q python3 python3-pip",
        "install": "pip3 install -q {pkg}", "prog": "/p.py", "run": "python3 /p.py"},
    "amazonlinux:2": {"lang": "python", "bootstrap": "yum install -y -q python3 python3-pip",
        "install": "pip3 install -q {pkg}", "prog": "/p.py", "run": "python3 /p.py"},

    # Node: package installs land in /tmp/node_modules, so run from /tmp.
    "node:18": {"lang": "node", "workdir": "/tmp", "install": "npm install --silent --no-save {pkg}",
        "prog": "p.js", "run": "node p.js"},
    "node:20": {"lang": "node", "workdir": "/tmp", "install": "npm install --silent --no-save {pkg}",
        "prog": "p.js", "run": "node p.js"},
    "node:22": {"lang": "node", "workdir": "/tmp", "install": "npm install --silent --no-save {pkg}",
        "prog": "p.js", "run": "node p.js"},
    "node:20-alpine": {"lang": "node", "workdir": "/tmp", "install": "npm install --silent --no-save {pkg}",
        "prog": "p.js", "run": "node p.js"},

    # Go: `go run` compiles and runs a single file. GOFLAGS gives it a scratch
    # cache/module dir; net/http is stdlib so nothing is downloaded.
    "golang:1.20": {"lang": "go", "env": "GOCACHE=/tmp/gc GO111MODULE=off", "prog": "/tmp/m.go", "run": "go run /tmp/m.go"},
    "golang:1.21": {"lang": "go", "env": "GOCACHE=/tmp/gc GO111MODULE=off", "prog": "/tmp/m.go", "run": "go run /tmp/m.go"},
    "golang:1.22": {"lang": "go", "env": "GOCACHE=/tmp/gc GO111MODULE=off", "prog": "/tmp/m.go", "run": "go run /tmp/m.go"},
    "golang:1.23": {"lang": "go", "env": "GOCACHE=/tmp/gc GO111MODULE=off", "prog": "/tmp/m.go", "run": "go run /tmp/m.go"},
    "golang:1.22-alpine": {"lang": "go", "env": "GOCACHE=/tmp/gc GO111MODULE=off", "prog": "/tmp/m.go", "run": "go run /tmp/m.go"},

    # Java: single-file source launch (JEP 330) compiles and runs M.java in one
    # JVM, honouring {cp}. No install; jars (if any) come from the client setup.
    "eclipse-temurin:11": {"lang": "java", "prog": "/M.java", "run": "java {cp} /M.java"},
    "eclipse-temurin:17": {"lang": "java", "prog": "/M.java", "run": "java {cp} /M.java"},
    "eclipse-temurin:21": {"lang": "java", "prog": "/M.java", "run": "java {cp} /M.java"},
    "eclipse-temurin:21-alpine": {"lang": "java", "prog": "/M.java", "run": "java {cp} /M.java"},

    # .NET: scaffold a console project, overwrite Program.cs, build to /out and
    # run the DLL directly so only the program's stdout reaches us. HOME/NuGet
    # caches point at /tmp so the SDK has somewhere writable.
    "mcr.microsoft.com/dotnet/sdk:6.0": {"lang": "dotnet",
        "env": "HOME=/tmp NUGET_PACKAGES=/tmp/nuget DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_CLI_HOME=/tmp",
        "scaffold": "dotnet new console -o /app", "prog": "/app/Program.cs",
        "run": "cd /app && dotnet build -c Release -v q --nologo -o /out >/dev/null 2>&1 && dotnet /out/app.dll"},
    "mcr.microsoft.com/dotnet/sdk:8.0": {"lang": "dotnet",
        "env": "HOME=/tmp NUGET_PACKAGES=/tmp/nuget DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_CLI_HOME=/tmp",
        "scaffold": "dotnet new console -o /app", "prog": "/app/Program.cs",
        "run": "cd /app && dotnet build -c Release -v q --nologo -o /out >/dev/null 2>&1 && dotnet /out/app.dll"},
    "mcr.microsoft.com/dotnet/sdk:9.0": {"lang": "dotnet",
        "env": "HOME=/tmp NUGET_PACKAGES=/tmp/nuget DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_CLI_HOME=/tmp",
        "scaffold": "dotnet new console -o /app", "prog": "/app/Program.cs",
        "run": "cd /app && dotnet build -c Release -v q --nologo -o /out >/dev/null 2>&1 && dotnet /out/app.dll"},
    "mcr.microsoft.com/dotnet/sdk:8.0-alpine": {"lang": "dotnet",
        "env": "HOME=/tmp NUGET_PACKAGES=/tmp/nuget DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_CLI_HOME=/tmp",
        "scaffold": "dotnet new console -o /app", "prog": "/app/Program.cs",
        "run": "cd /app && dotnet build -c Release -v q --nologo -o /out >/dev/null 2>&1 && dotnet /out/app.dll"},

    # Rust: scaffold a crate, drop the client's dependency line into Cargo.toml,
    # overwrite src/main.rs, and `cargo run`. native-tls needs OpenSSL headers,
    # so the Debian base gets libssl-dev and the Alpine base the static openssl.
    "rust:1-slim": {"lang": "rust", "env": "CARGO_HOME=/tmp/cargo",
        "bootstrap": "apt-get update -qq && apt-get install -y -qq pkg-config libssl-dev ca-certificates",
        "scaffold": "cargo new -q /app --name probe && "
                   "printf '[package]\\nname=\"probe\"\\nversion=\"0.0.0\"\\nedition=\"2021\"\\n"
                   "[dependencies]\\n%s\\nserde_json=\"1\"\\n' '{pkg}' > /app/Cargo.toml",
        "prog": "/app/src/main.rs", "run": "cd /app && cargo run -q"},
    "rust:1-alpine": {"lang": "rust", "env": "CARGO_HOME=/tmp/cargo",
        "bootstrap": "apk add --no-cache openssl-dev openssl-libs-static pkgconfig musl-dev",
        "scaffold": "cargo new -q /app --name probe && "
                   "printf '[package]\\nname=\"probe\"\\nversion=\"0.0.0\"\\nedition=\"2021\"\\n"
                   "[dependencies]\\n%s\\nserde_json=\"1\"\\n' '{pkg}' > /app/Cargo.toml",
        "prog": "/app/src/main.rs", "run": "cd /app && cargo run -q"},
}

STARTER = {
    "python": {
        "clients": ["py urllib (stdlib)", "py requests", "py httpx", "py aiohttp"],
        "images": ["python:3.11-slim", "python:3.11-alpine", "amazonlinux:2023"],
    },
    "node": {
        "clients": ["node https (stdlib)", "node fetch (global)", "node undici", "node axios", "node got"],
        "images": ["node:18", "node:20", "node:22", "node:20-alpine"],
    },
    "go": {
        "clients": ["go net/http (stdlib)"],
        "images": ["golang:1.20", "golang:1.22", "golang:1.23", "golang:1.22-alpine"],
    },
    "java": {
        "clients": ["java java.net.http (stdlib)", "java okhttp", "java apache httpclient5"],
        "images": ["eclipse-temurin:11", "eclipse-temurin:17", "eclipse-temurin:21", "eclipse-temurin:21-alpine"],
    },
    "dotnet": {
        "clients": ["dotnet HttpClient (stdlib)"],
        "images": ["mcr.microsoft.com/dotnet/sdk:6.0", "mcr.microsoft.com/dotnet/sdk:8.0",
                   "mcr.microsoft.com/dotnet/sdk:9.0", "mcr.microsoft.com/dotnet/sdk:8.0-alpine"],
    },
    "rust": {
        "clients": ["rust reqwest (native-tls)", "rust reqwest (rustls)", "rust ureq (rustls)"],
        "images": ["rust:1-slim", "rust:1-alpine"],
    },
}

LANGS = ["python", "node", "go", "java", "dotnet", "rust"]


def run_cell(client: str, image: str, timeout: int) -> dict:
    c, e = CLIENTS[client], ENVIRONMENTS[image]
    steps: list[str] = []
    # One export up front. Every step shares the one `sh -c`, so this reaches
    # both the install (e.g. `dotnet new` wanting a writable HOME) and the run.
    if e.get("env"):
        steps.append("export " + e["env"])
    if e.get("bootstrap"):
        steps.append("{ " + e["bootstrap"] + " ; } >/dev/null 2>&1")
    if e.get("workdir"):
        steps.append("cd " + e["workdir"])
    if c.get("setup"):
        steps.append("{ " + c["setup"] + " ; } >/dev/null 2>&1")
    # A scaffold (a compiled language's empty project) always runs; an install
    # (pip/npm) only when the client actually names a package, so stdlib clients
    # skip it. Both take {pkg} by str.replace, not str.format — a Cargo.toml
    # dependency line is full of the braces str.format would choke on.
    # Wrapped in a brace group so the quieting redirect is the group default and
    # does NOT clobber an inner one — a scaffold may end in `printf ... > f`, and
    # a bare trailing `>/dev/null` would win the fd and truncate f to empty.
    if e.get("scaffold"):
        steps.append("{ " + e["scaffold"].replace("{pkg}", c.get("pkg") or "") + " ; } >/dev/null 2>&1")
    if c.get("pkg") and e.get("install"):
        steps.append("{ " + e["install"].replace("{pkg}", c["pkg"]) + " ; } >/dev/null 2>&1")
    steps.append("cat > " + e["prog"])
    steps.append(e["run"].replace("{cp}", c.get("cp", "")))
    shell = " && ".join(steps)
    try:
        proc = subprocess.run(
            ["docker", "run", "--rm", "-i", image, "sh", "-c", shell],
            input=c["code"], capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"client": client, "image": image, "error": "timeout"}
    out = proc.stdout.strip()
    if proc.returncode != 0 or "\t" not in out:
        reason = (proc.stderr.strip().splitlines() or ["failed"])[-1][:80]
        return {"client": client, "image": image, "error": reason}
    ja4, ja3 = out.split("\t", 1)
    return {"client": client, "image": image, "ja4": ja4.strip(), "ja3": ja3.strip()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", choices=LANGS, action="append", help="only this language (repeatable)")
    parser.add_argument("--full", action="store_true", help="every client on every image")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    langs = args.lang or LANGS
    cells: list[tuple[str, str]] = []
    for lang in langs:
        if args.full:
            clients = [c for c, v in CLIENTS.items() if v["lang"] == lang]
            images = [i for i, v in ENVIRONMENTS.items() if v["lang"] == lang]
            cells += [(c, i) for i in images for c in clients]
        else:
            cells += [(c, i) for i in STARTER[lang]["images"] for c in STARTER[lang]["clients"]]

    print(f"running {len(cells)} cells, {args.jobs} at a time\n")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_cell, c, i, args.timeout): (c, i) for c, i in cells}
        for fut in concurrent.futures.as_completed(futures):
            r = fut.result()
            results.append(r)
            mark = r.get("ja4") or f"— {r.get('error')}"
            print(f"  {r['image']:44s} {r['client']:30s} {mark}")

    results.sort(key=lambda r: (r["image"], r["client"]))
    here = pathlib.Path(__file__).parent
    (here / "catalog.json").write_text(json.dumps(results, indent=2))
    lines = ["# TLS fingerprint catalog", "", "Ground truth: known client × environment → JA4, via tls.peet.ws.",
             "", "| image | client | JA4 | JA3 |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| `{r['image']}` | {r['client']} | `{r.get('ja4') or '*'+str(r.get('error'))+'*'}` | `{r.get('ja3','')}` |")
    (here / "catalog.md").write_text("\n".join(lines) + "\n")

    ok = [r for r in results if r.get("ja4")]
    print(f"\n{len(ok)}/{len(results)} cells produced a fingerprint")
    print(f"wrote catalog.md and catalog.json to {here}")


if __name__ == "__main__":
    sys.exit(main())
