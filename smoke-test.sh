#!/usr/bin/env bash
# Smoke test for the deployed /process endpoint.
# Hits a couple of known videos and checks the response for the failure
# modes we've hit before (bad format selection, HLS timeouts, missing
# subtitles, broken screenshots), then prints a PASS/FAIL summary.
#
# Usage: ./smoke-test.sh [base_url]
#   base_url defaults to the production server.

set -u

BASE_URL="${1:-http://34.127.52.76:5000}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

PASS_COUNT=0
FAIL_COUNT=0
FAILURES=()

# run_case <name> <youtube_url> <start> <end> <subtitle_mode>
# subtitle_mode: "none"    -> expect the "no subtitles" placeholder
#                "present" -> expect real, non-empty subtitle text
run_case() {
  local name="$1" url="$2" start="$3" end="$4" subtitle_mode="$5"
  local html="$TMP_DIR/${name// /_}.html"
  local case_fail=""

  local http_code
  http_code=$(curl -s -o "$html" -w "%{http_code}" --max-time 90 -X POST "$BASE_URL/process" \
    -d "youtube_url=$url" -d "start_time=$start" -d "end_time=$end" -d "lang=en")

  if [ "$http_code" != "200" ]; then
    case_fail="HTTP status was $http_code, expected 200"
  fi

  if [ -z "$case_fail" ] && grep -q 'class="error-box"' "$html"; then
    local err_msg
    err_msg=$(grep -o 'class="error-box">[^<]*' "$html" | sed 's/^[^>]*>//')
    case_fail="error-box present: $err_msg"
  fi

  local download_name=""
  if [ -z "$case_fail" ]; then
    download_name=$(grep -o 'download="[^"]*"' "$html" | head -1 | sed 's/download="//;s/"$//')
    if [ -z "$download_name" ]; then
      case_fail="no download filename found in response"
    fi
  fi

  local subtitle_text=""
  if [ -z "$case_fail" ]; then
    subtitle_text=$(sed -n 's/.*id="subtitle-text">\(.*\)<\/div>.*/\1/p' "$html" | head -1)
    if [ "$subtitle_mode" = "none" ]; then
      if [[ "$subtitle_text" != *"No subtitles available"* ]]; then
        case_fail="expected the no-subtitles placeholder, got: $subtitle_text"
      fi
    else
      if [ -z "$subtitle_text" ] || [[ "$subtitle_text" == *"No subtitles available"* ]] || [[ "$subtitle_text" == *"Failed to fetch subtitles"* ]]; then
        case_fail="expected real subtitle text, got: $subtitle_text"
      fi
    fi
  fi

  local frame_url=""
  if [ -z "$case_fail" ]; then
    frame_url=$(grep -o 'src="/outputs/[^"]*"' "$html" | head -1 | sed 's/src="//;s/"$//')
    if [ -z "$frame_url" ]; then
      case_fail="no screenshot <img> src found in response"
    fi
  fi

  if [ -z "$case_fail" ]; then
    local img_file="$TMP_DIR/${name// /_}.jpg"
    local img_http_code
    img_http_code=$(curl -s -o "$img_file" -w "%{http_code}" --max-time 30 "$BASE_URL$frame_url")
    if [ "$img_http_code" != "200" ]; then
      case_fail="screenshot download returned HTTP $img_http_code"
    else
      local file_type
      file_type=$(file -b "$img_file" 2>/dev/null)
      if [[ "$file_type" != *"JPEG image data"* ]]; then
        case_fail="downloaded screenshot is not a valid JPEG (file: $file_type)"
      fi
    fi
  fi

  if [ -z "$case_fail" ]; then
    echo "PASS  $name  (download=\"$download_name\")"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "FAIL  $name -- $case_fail"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("$name: $case_fail")
  fi
}

echo "Smoke testing $BASE_URL ..."
echo

run_case "ZhjqwrcdEpw (no captions, HLS-timeout repro)" \
  "https://www.youtube.com/watch?v=ZhjqwrcdEpw" "10" "20" "none"

run_case "5MuIMqhT8DM (has YouTube captions)" \
  "https://www.youtube.com/watch?v=5MuIMqhT8DM" "10" "20" "present"

echo
if [ "$FAIL_COUNT" -eq 0 ]; then
  echo "RESULT: ALL PASS ($PASS_COUNT/$((PASS_COUNT + FAIL_COUNT)))"
  exit 0
else
  echo "RESULT: FAIL ($FAIL_COUNT/$((PASS_COUNT + FAIL_COUNT)) failed)"
  for f in "${FAILURES[@]}"; do
    echo "  - $f"
  done
  exit 1
fi
