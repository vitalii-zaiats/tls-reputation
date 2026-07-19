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
program is fed to the interpreter over stdin (via a temp file), so there is no
shell-quoting to get wrong.

Usage:
    python matrix.py                 # the starter grid (both languages)
    python matrix.py --lang node     # one language
    python matrix.py --full          # every client on every image (slow)
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
}

# Each environment: the language it provides, an optional bootstrap to install
# the runtime, how to install a package, and how to run the temp program.
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
}


def run_cell(client: str, image: str, timeout: int) -> dict:
    c, e = CLIENTS[client], ENVIRONMENTS[image]
    steps: list[str] = []
    if e.get("bootstrap"):
        steps.append(e["bootstrap"] + " >/dev/null 2>&1")
    if e.get("workdir"):
        steps.append("cd " + e["workdir"])
    if c["pkg"]:
        steps.append(e["install"].format(pkg=c["pkg"]) + " >/dev/null 2>&1")
    steps.append("cat > " + e["prog"])
    steps.append((e["env"] + " " if e.get("env") else "") + e["run"])
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
    parser.add_argument("--lang", choices=["python", "node", "go"], help="one language only")
    parser.add_argument("--full", action="store_true", help="every client on every image")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    langs = [args.lang] if args.lang else ["python", "node", "go"]
    cells: list[tuple[str, str]] = []
    for lang in langs:
        if args.full:
            clients = [c for c, v in CLIENTS.items() if v["lang"] == lang]
            images = [i for i, v in ENVIRONMENTS.items() if v["lang"] == lang]
        else:
            clients, images = STARTER[lang]["clients"], STARTER[lang]["images"]
        cells += [(c, i) for i in images for c in clients]

    print(f"running {len(cells)} cells, {args.jobs} at a time\n")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_cell, c, i, args.timeout): (c, i) for c, i in cells}
        for fut in concurrent.futures.as_completed(futures):
            r = fut.result()
            results.append(r)
            mark = r.get("ja4") or f"— {r.get('error')}"
            print(f"  {r['image']:24s} {r['client']:24s} {mark}")

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
