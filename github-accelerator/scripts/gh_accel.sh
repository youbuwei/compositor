#!/usr/bin/env bash
# gh_accel.sh - GitHub 网络加速工具（直连优先，镜像兜底；仅只读操作）
# 镜像/加速代理一律由用户在本地配置文件中自行接入（不内置任何第三方域名，
# 第三方镜像属于不可信转发方，应由用户自己选择信任谁）：
#   ~/.config/gh-accelerator/proxies.conf   （可用环境变量 GH_ACCEL_CONFIG 覆盖路径）
# 输出语言: GH_ACCEL_LANG=zh（默认，面向 CN 网络用户）或 en
# 依赖: curl, git, sha256sum/shasum。镜像状态易变，用前建议先跑 check。
# 内容完整性：镜像仅作传输层。raw 文件按官方 git blob sha1 校验、Release 资产按
# 官方 sha256 digest 校验（均取自 api.github.com 直连）；镜像 clone 按官方
# ls-remote 的 HEAD 比对。拿不到官方摘要时，镜像下载一律拒绝落盘（--sha256 可显式指定）。
set -uo pipefail

CONFIG_FILE="${GH_ACCEL_CONFIG:-$HOME/.config/gh-accelerator/proxies.conf}"
LANG_SEL="${GH_ACCEL_LANG:-zh}"

# msg <zh-text> <en-text>
msg() {
  if [ "$LANG_SEL" = "en" ]; then printf '%s\n' "$2"; else printf '%s\n' "$1"; fi
}

# 镜像梯次：默认为空。所有镜像/加速域名由用户经本地配置注入（见文件头），
# 脚本不内置、也不推荐任何第三方镜像——由用户选择信任谁。
DL_PROXIES=()
CLONE_PROXIES=()
TEST_RAW="https://raw.githubusercontent.com/hunshcn/gh-proxy/master/README.md"

# ---------- 本地私有代理加载（排在公共梯次之前） ----------
# 格式（每行一条，# 注释；裸域名自动补 https://）:
#   DOWNLOAD_PROXY=https://your-proxy.example.com
#   CLONE_PROXY=https://your-proxy.example.com/https://github.com
LOCAL_DL=(); LOCAL_CLONE=()
if [ ! -f "$CONFIG_FILE" ]; then
  mkdir -p "$(dirname "$CONFIG_FILE")" 2>/dev/null \
    && cat > "$CONFIG_FILE" <<'TMPL' 2>/dev/null || true
# gh-accelerator 本地私有代理配置（机器本地文件，禁止提交到仓库）
# Local private proxy config. Machine-local; never commit it.
# 每行一条，去掉行首 # 并改成你的代理地址即可生效；会自动排在公共镜像之前。
# One entry per line: uncomment and set your proxy; local entries outrank public mirrors.
# DOWNLOAD_PROXY=https://your-proxy.example.com
# CLONE_PROXY=https://your-proxy.example.com/https://github.com
TMPL
  true
fi
if [ -f "$CONFIG_FILE" ]; then
  while IFS= read -r line; do
    line="${line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"; line="${line%"${line##*[![:space:]]}"}"
    [ -z "$line" ] && continue
    case "$line" in
      DOWNLOAD_PROXY=*)
        v="${line#DOWNLOAD_PROXY=}"; case "$v" in http*) ;; *) v="https://$v";; esac
        LOCAL_DL+=("$v") ;;
      CLONE_PROXY=*)
        v="${line#CLONE_PROXY=}"; case "$v" in http*) ;; *) v="https://$v";; esac
        LOCAL_CLONE+=("$v") ;;
    esac
  done < "$CONFIG_FILE"
fi
DL_PROXIES=(${LOCAL_DL[@]+"${LOCAL_DL[@]}"})
CLONE_PROXIES=(${LOCAL_CLONE[@]+"${LOCAL_CLONE[@]}"})

is_local() {
  local u
  for u in "${LOCAL_DL[@]+"${LOCAL_DL[@]}"}" "${LOCAL_CLONE[@]+"${LOCAL_CLONE[@]}"}"; do
    [ "$u" = "$1" ] && return 0
  done
  return 1
}

# 仅接受 GitHub 官方域名的 https URL；拒绝查询串/片段与内嵌凭据，避免令牌经镜像泄露。
github_url_ok() {
  [[ "$1" =~ ^https://[^/@]+@ ]] && return 3
  case "$1" in
    https://github.com/*|\
    https://raw.githubusercontent.com/*|\
    https://gist.githubusercontent.com/*|\
    https://objects.githubusercontent.com/*|\
    https://release-assets.githubusercontent.com/*|\
    https://github-releases.githubusercontent.com/*|\
    https://codeload.github.com/*) ;;
    *) return 1 ;;
  esac
  case "$1" in
    *\?*|*\#*) return 2 ;;
  esac
  return 0
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    return 1
  fi
}

# git blob sha1（与 contents API 返回的 .sha 同口径），用于 raw 文件校验
blob_sha1() { git hash-object "$1" 2>/dev/null; }

# api_get <endpoint> — 官方 REST API 直连取 JSON（gh 优先，匿名 curl 兜底）。
# 成功时设置 API_BODY 并返回 0。api.github.com 是本技能的校验通道。
api_get() {
  API_BODY=""
  if command -v gh >/dev/null 2>&1; then
    if API_BODY=$(gh api "$1" 2>/dev/null); then return 0; fi
  fi
  API_BODY=$(curl -s --max-time 15 "https://api.github.com/$1" 2>/dev/null) || return 1
  [ -n "$API_BODY" ]
}

# expected_digest <github-url> — 回显官方摘要 "algo:hash"（sha1:… / sha256:…），
# 无法确定时返回 1。ref 含斜杠的 raw URL 与 archive 无法自动校验。
expected_digest() {
  case "$1" in
    https://raw.githubusercontent.com/*)
      local rest="${1#https://raw.githubusercontent.com/}"
      local owner="${rest%%/*}"; rest="${rest#*/}"
      local repo="${rest%%/*}"; rest="${rest#*/}"
      local ref="${rest%%/*}"; local path="${rest#*/}"
      [ -n "$path" ] && [ "$path" != "$rest" ] || return 1
      api_get "repos/$owner/$repo/contents/$path?ref=$ref" || return 1
      local h
      h=$(printf '%s' "$API_BODY" | grep -o '"sha": *"[0-9a-f]\{40\}"' | head -1 | grep -o '[0-9a-f]\{40\}')
      [ -n "$h" ] || return 1
      printf 'sha1:%s' "$h" ;;
    https://github.com/*/*/releases/download/*)
      local rest="${1#https://github.com/}"
      local owner="${rest%%/*}"; rest="${rest#*/}"
      local repo="${rest%%/*}"
      local tail="${rest#*/releases/download/}"
      local tag="${tail%%/*}"; local file="${tail#*/}"
      # 结构化解析（资产对象内嵌套 uploader 等，正则切分会误伤）：gh --jq 优先，python3 兜底
      local d=""
      if command -v gh >/dev/null 2>&1; then
        d=$(gh api "repos/$owner/$repo/releases/tags/$tag" \
             --jq ".assets[] | select(.name == \"$file\") | .digest" 2>/dev/null | head -1)
      fi
      if [ -z "$d" ] && command -v python3 >/dev/null 2>&1 \
         && api_get "repos/$owner/$repo/releases/tags/$tag"; then
        d=$(printf '%s' "$API_BODY" | python3 -c 'import json,sys
for a in json.load(sys.stdin).get("assets", []):
    if a.get("name") == sys.argv[1] and a.get("digest"):
        print(a["digest"]); break
' "$file" 2>/dev/null)
      fi
      case "$d" in
        sha256:*) printf '%s' "$d" ;;
        *) return 1 ;;
      esac ;;
    *) return 1 ;;
  esac
}

usage() {
  msg "用法:" "Usage:"
  msg "  gh_accel.sh check                        探测直连与各镜像可用性" \
      "  gh_accel.sh check                        probe direct links and mirrors"
  msg "  gh_accel.sh dl [--no-direct] [--sha256 H] <github-url>" \
      "  gh_accel.sh dl [--no-direct] [--sha256 H] <github-url>"
  msg "  gh_accel.sh clone [--no-direct] <owner/repo> [dir]" \
      "  gh_accel.sh clone [--no-direct] <owner/repo> [dir]"
  msg "" ""
  msg "仅接受 GitHub 官方域名 URL；目标文件已存在时拒绝覆盖。" \
      "Only official GitHub-host URLs are accepted; existing output files are never overwritten."
  msg "语言: GH_ACCEL_LANG=zh|en（默认 zh）" \
      "Language: GH_ACCEL_LANG=zh|en (default: zh)"
  msg "本地私有代理配置: \$GH_ACCEL_CONFIG（默认 ~/.config/gh-accelerator/proxies.conf）" \
      "Private proxies: \$GH_ACCEL_CONFIG (default: ~/.config/gh-accelerator/proxies.conf)"
  exit 1
}

# fetch <url> <outfile> <max-sec> -> echo http_code (000=失败)
fetch() {
  local code rc
  code=$(curl -sL --max-time "$3" -o "$2" -w '%{http_code}' "$1" 2>/dev/null)
  rc=$?
  [ $rc -ne 0 ] && code=000
  echo "${code:-000}"
}

# probe <url> <max-sec> -> echo http_code (000=失败)；不跟随重定向，2xx/3xx/404 均视为存活
probe() {
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time "$2" "$1" 2>/dev/null)
  [ $? -ne 0 ] && code="000"
  echo "${code:-000}"
}

cmd_check() {
  echo "本地配置: $CONFIG_FILE ($((${#LOCAL_DL[@]} + ${#LOCAL_CLONE[@]})) 条私有代理)"
  echo "== 直连探测 =="
  for d in "api.github.com/zen" "$TEST_RAW" "codeload.github.com/hunshcn/gh-proxy/tar.gz/master" "github.com/"; do
    code=$(probe "https://$d" 8)
    case "$code" in
      200|301|302|404) echo "  ✓ $d ($code)" ;;
      *)               echo "  ✗ $d ($code)" ;;
    esac
  done
  echo "== 下载镜像（拉测试文件验内容）=="
  if [ "${#DL_PROXIES[@]}" -eq 0 ]; then
    echo "  （未配置任何下载镜像；在 $CONFIG_FILE 添加 DOWNLOAD_PROXY= 行接入，见 SKILL.md §5.1）"
  fi
  for p in ${DL_PROXIES[@]+"${DL_PROXIES[@]}"}; do
    tag=""; is_local "$p" && tag="  [本地]"
    out=$(mktemp)
    code=$(fetch "$p/$TEST_RAW" "$out" 15)
    if [ "$code" = "200" ] && grep -q "gh-proxy" "$out" 2>/dev/null; then
      echo "  ✓ $p$tag"
    else
      echo "  ✗ $p$tag (http=$code)"
    fi
    rm -f "$out"
  done
  echo "== clone 镜像（ls-remote 探测公开仓库）=="
  if [ "${#CLONE_PROXIES[@]}" -eq 0 ]; then
    echo "  （未配置任何 clone 镜像；在 $CONFIG_FILE 添加 CLONE_PROXY= 行接入，见 SKILL.md §5.1）"
  fi
  for base in ${CLONE_PROXIES[@]+"${CLONE_PROXIES[@]}"}; do
    tag=""; is_local "$base" && tag="  [本地]"
    if timeout 20 git ls-remote "$base/hunshcn/gh-proxy.git" HEAD >/dev/null 2>&1; then
      echo "  ✓ $base$tag"
    else
      echo "  ✗ $base$tag"
    fi
  done
}

cmd_dl() {
  local no_direct=0 expect_sha="" url=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --no-direct) no_direct=1 ;;
      --sha256)
        [ $# -ge 2 ] || usage
        expect_sha="$2"; shift ;;
      -*) usage ;;
      *)
        [ -z "$url" ] || usage
        url="$1" ;;
    esac
    shift
  done
  [ -n "$url" ] || usage

  case "$url" in
    https://*) ;;
    http://*) url="https://${url#http://}" ;;
    *) url="https://$url" ;;
  esac
  github_url_ok "$url"
  case $? in
    1) msg "❌ 仅支持 GitHub 官方域名 URL（github.com / *.githubusercontent.com / codeload.github.com）" \
           "ERROR: only official GitHub-host URLs are supported"; return 1 ;;
    2) msg "❌ 拒绝含查询串/片段的 URL（可能携带令牌）" \
           "ERROR: URLs with query strings or fragments are rejected (possible token leakage)"; return 1 ;;
    3) msg "❌ 拒绝内嵌凭据的 URL" \
           "ERROR: URLs with embedded credentials are rejected"; return 1 ;;
  esac

  local out="$(basename "${url%%\?*}")"
  [ -z "$out" ] && out="download.bin"
  case "$out" in
    -*) msg "❌ 拒绝非安全文件名: $out" "ERROR: unsafe output filename: $out"; return 1 ;;
  esac
  if [ -e "$out" ]; then
    msg "❌ 目标文件已存在，拒绝覆盖: $out（请先移走或改名）" \
        "ERROR: output file already exists, refusing to overwrite: $out"
    return 1
  fi
  local tmp="$(mktemp "./.${out}.XXXXXX")"

  # 官方摘要（raw→git blob sha1；release 资产→sha256 digest；拿不到则为空）
  local expected=""
  expected="$(expected_digest "$url")" || expected=""
  if [ -n "$expect_sha" ]; then expected="sha256:$expect_sha"; fi

  local code got_sha p
  try_channel() {
    code=$(fetch "$1" "$tmp" "$2")
    if [ "$code" = "200" ] && [ -s "$tmp" ]; then
      local via_official=1
      case "$3" in 直连*|direct*) ;; *) via_official=0 ;; esac
      if [ -z "$expected" ] && [ "$via_official" -eq 0 ]; then
        rm -f "$tmp"
        msg "  ✗ 拿不到官方摘要，无法校验镜像内容，拒绝落盘（提供 --sha256 可显式校验）" \
            "  FAIL: no official digest to verify mirror content; refusing (pass --sha256 to pin)"
        return 1
      fi
      if [ -n "$expected" ]; then
        local algo="${expected%%:*}" hash="${expected#*:}" mine=""
        if [ "$algo" = "sha256" ]; then
          mine="$(sha256_file "$tmp")" || { rm -f "$tmp"
            msg "  ✗ 无法计算 sha256（缺少 sha256sum/shasum）" \
                "  FAIL: cannot compute sha256 (sha256sum/shasum missing)"; return 1; }
        else
          mine="$(blob_sha1 "$tmp")"
        fi
        if [ -z "$mine" ] || [ "$mine" != "$hash" ]; then
          rm -f "$tmp"
          msg "  ✗ 校验失败：官方 ${algo} ${hash:0:12}…，得到 ${mine:0:12}…（截断/篡改？），换下一通道" \
              "  FAIL: ${algo} mismatch (official ${hash:0:12}..., got ${mine:0:12}...); trying next channel"
          return 1
        fi
      fi
      mv "$tmp" "$out" || { rm -f "$tmp"; return 1; }
      got_sha="$(sha256_file "$out" 2>/dev/null)" || got_sha="unknown"
      msg "✅ 经 $3 下载成功 -> $out ($(du -h "$out" | cut -f1), sha256=$got_sha)" \
          "OK: downloaded via $3 -> $out ($(du -h "$out" | cut -f1), sha256=$got_sha)"
      if [ -n "$expected" ]; then
        msg "  ✓ 内容已按官方摘要校验（${expected%%:*}）" \
            "  verified against the official digest (${expected%%:*})"
      else
        msg "⚠️  官方源无摘要可比对（archive/gist 等），已回显 sha256，请自行核对" \
            "WARN: no digest available for this URL; verify the printed sha256 yourself"
      fi
      return 0
    fi
    rm -f "$tmp"
    return 1
  }

  if [ $no_direct -eq 0 ]; then
    msg "→ 直连: $url" "-> direct: $url"
    try_channel "$url" 60 "直连/direct" && return 0
    msg "  ✗ 直连失败 (http=$code)，降级镜像…" "  FAIL: direct link (http=$code), falling back to mirrors..."
  fi

  for p in ${DL_PROXIES[@]+"${DL_PROXIES[@]}"}; do
    msg "→ 镜像: $p" "-> mirror: $p"
    try_channel "$p/$url" 90 "$p" && return 0
    msg "  ✗ $p 失败 (http=$code)" "  FAIL: $p (http=$code)"
  done
  rm -f "$tmp"
  msg "❌ 全部通道失败。跑 'gh_accel.sh check' 看状态；未配置镜像时在 proxies.conf 接入（SKILL.md §5.1）" \
      "ERROR: all channels failed. Run 'gh_accel.sh check'; add a mirror in proxies.conf (SKILL.md §5.1) if none is configured"
  return 1
}

cmd_clone() {
  local no_direct=0 repo="" dir="" dir_pre_existed=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --no-direct) no_direct=1 ;;
      -*) usage ;;
      *)
        if [ -z "$repo" ]; then repo="$1"
        elif [ -z "$dir" ]; then dir="$1"
        else usage; fi ;;
    esac
    shift
  done
  [ -n "$repo" ] || usage
  repo="${repo#https://github.com/}"; repo="${repo%.git}"
  case "$repo" in
    */*/*|.*|*..*|*[[:space:]]*|"") msg "❌ 非法仓库标识: $repo（格式 owner/repo）" \
                                       "ERROR: invalid repository id: $repo (expected owner/repo)"; return 1 ;;
  esac
  [ -z "$dir" ] && dir="$(basename "$repo")"
  case "$dir" in
    -*) msg "❌ 拒绝非安全目录名: $dir" "ERROR: unsafe destination directory: $dir"; return 1 ;;
  esac
  if [ -e "$dir" ] && [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then
    msg "❌ 目标目录已存在且非空，拒绝克隆: $dir" \
        "ERROR: destination exists and is not empty, refusing to clone: $dir"
    return 1
  fi
  [ -e "$dir" ] && dir_pre_existed=1

  if [ $no_direct -eq 0 ]; then
    msg "→ 直连: https://github.com/$repo" "-> direct: https://github.com/$repo"
    if git clone "https://github.com/$repo" "$dir"; then
      msg "✅ 直连 clone 成功 -> $dir" "OK: direct clone -> $dir"
      return 0
    fi
    if [ "$dir_pre_existed" -eq 0 ]; then rmdir "$dir" 2>/dev/null || true; fi
    msg "  ✗ 直连失败，降级镜像…" "  FAIL: direct clone, falling back to mirrors..."
  fi

  for base in ${CLONE_PROXIES[@]+"${CLONE_PROXIES[@]}"}; do
    msg "→ 镜像: $base/$repo" "-> mirror: $base/$repo"
    if git clone "$base/$repo" "$dir"; then
      # 与官方 HEAD 比对：镜像可能给错内容/旧缓存
      local got_head official_head
      got_head="$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)"
      official_head="$(timeout 20 git ls-remote "https://github.com/$repo.git" HEAD 2>/dev/null | awk '{print $1}')"
      if [ -n "$official_head" ] && [ -n "$got_head" ] && [ "$official_head" != "$got_head" ]; then
        [ "$dir_pre_existed" -eq 0 ] && rm -rf "$dir"
        msg "  ✗ HEAD 与官方不一致（$(echo "$got_head" | cut -c1-12) ≠ $(echo "$official_head" | cut -c1-12)），丢弃" \
            "  FAIL: HEAD differs from official; discarding"
        continue
      fi
      if [ -z "$official_head" ]; then
        msg "⚠️  官方 ls-remote 不可达，未能校验 HEAD，请自行核对 git log 后再使用" \
            "WARN: official ls-remote unreachable; verify the commit log yourself"
      fi
      # 校验通过（或无法校验但已警告）：恢复官方 remote，避免误推到镜像
      git -C "$dir" remote set-url origin "https://github.com/$repo.git"
      msg "✅ 经镜像 clone 成功 -> $dir（remote 已恢复官方源）" \
          "OK: mirror clone -> $dir (remote restored to the official origin)"
      return 0
    fi
    if [ "$dir_pre_existed" -eq 0 ]; then rmdir "$dir" 2>/dev/null || true; fi
    msg "  ✗ 失败" "  FAIL"
  done
  msg "❌ 全部通道失败。跑 'gh_accel.sh check' 探测" "ERROR: all channels failed. Run 'gh_accel.sh check'."
  return 1
}

[ $# -lt 1 ] && usage
case "$1" in
  check) cmd_check ;;
  dl)    [ $# -ge 2 ] || usage; cmd_dl "${@:2}" ;;
  clone) [ $# -ge 2 ] || usage; cmd_clone "${@:2}" ;;
  *)     usage ;;
esac
