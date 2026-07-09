# mixcrawler

> Multi-source 90-day crawler — **Reddit + Hacker News + Google News**, searchable by **keywords and full phrases**.
> 여러 소스(**Reddit + Hacker News + Google News**)를 **키워드와 문장(구문) 둘 다로** 검색해 지난 N일치 원문을 수집합니다.

Raw results are saved loss-less to `JSONL` and spreadsheet-friendly `CSV`.
The only dependency is `requests` — everything else is the Python standard library.

원문은 손실 없이 `JSONL`로, 엑셀용으로 `CSV`로 저장됩니다. 의존성은 `requests` 하나뿐, 나머지는 전부 파이썬 표준 라이브러리입니다.

```bash
python3 -m pip install requests
python3 crawler.py                 # uses config.json / config.json 사용
python3 crawler.py --days 30 --keywords "tesla,ev" --phrases "battery fire"
```

---

## English

### Source reality (2026, actually tested)

| Source | Auth | Last 90 days | Status |
|--------|------|--------------|--------|
| **Hacker News** (Algolia API) | none | ✅ | works out of the box |
| **Google News** (RSS `when:90d`) | none | ✅ | works out of the box |
| **Reddit** | **required** | ✅ (OAuth) | see below |

> As of 2026, unauthenticated `reddit.com/.json` returns **403**, and old Pushshift-style
> archives (PullPush) lag ~1 year behind, so they can't cover "the last 90 days".
> Two working paths are supported:
>
> - **A) OAuth (recommended)** — searches all of Reddit for the last 90 days. Free app, ~2 min.
> - **B) Arctic Shift (no auth)** — free Pushshift successor, but full-text search **must be scoped to a subreddit**.

#### Reddit OAuth setup (path A, recommended)

1. Go to https://www.reddit.com/prefs/apps → **create app** → type **script**.
2. Put the `client_id` (string under the app name) and `secret` into `config.json`:

```json
"reddit": {
  "enabled": true,
  "limit_per_query": 300,
  "subreddit": null,
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_SECRET"
}
```

No PRAW or extra library — it hits `oauth.reddit.com` directly with `requests`.

#### Reddit without auth (path B)

To scan a single subreddit without credentials, set `"subreddit": "worldnews"`.
It then collects via Arctic Shift with no auth. (Searching *all* of Reddit needs path A.)

### Output

`output/crawl_<timestamp>.jsonl` (loss-less) and `.csv` (Excel, UTF-8 BOM).
Common schema across every source:

```
source, id, created_utc(ISO8601 UTC), title, text, url, author,
score, subreddit, query, matched_keywords, matched_phrases
```

Same columns regardless of source, so downstream analysis is uniform.

### Next steps (raw → analysis)

- **Keyword frequency / time trends**: bucket by `created_utc`, count `matched_keywords`.
- **Sentiment**: split `title + text` into sentences → sentiment model (`vaderSentiment` for EN, `Kiwi`/`KoNLPy` for KO).
- **Full article text**: Google News gives only a summary — pass `url` to `newspaper4k` (`pip install newspaper4k`) for full text.

---

## 한국어

### 소스별 현실 (2026년 기준, 실제 테스트함)

| 소스 | 인증 | 지난 90일 | 상태 |
|------|------|-----------|------|
| **Hacker News** (Algolia API) | 불필요 | ✅ | 바로 됨 |
| **Google News** (RSS `when:90d`) | 불필요 | ✅ | 바로 됨 |
| **Reddit** | **필요** | ✅ (OAuth) | 아래 참고 |

> 2026년 현재 무인증 `reddit.com/.json` 접근은 **403**으로 막혔고, 옛 Pushshift 계열
> 아카이브(PullPush)는 데이터가 ~1년 뒤처져서 "최근 90일"을 못 채웁니다.
> 그래서 두 가지 합법 경로를 지원합니다:
>
> - **A) OAuth (추천)** — 레딧 전체를 최근 90일까지 검색. 무료 앱 등록 2분.
> - **B) Arctic Shift (무인증)** — Pushshift 후속 무료 아카이브. 단, 전체 텍스트 검색은 **subreddit 지정 필수**.

#### Reddit OAuth 설정 (경로 A, 추천)

1. https://www.reddit.com/prefs/apps → **create app** → 타입 **script** 선택
2. 발급된 `client_id`(앱 이름 밑 문자열)와 `secret`을 `config.json`에 입력:

```json
"reddit": {
  "enabled": true,
  "limit_per_query": 300,
  "subreddit": null,
  "client_id": "여기에_client_id",
  "client_secret": "여기에_secret"
}
```

PRAW 같은 추가 라이브러리 없이 `requests`로 `oauth.reddit.com`에 직접 붙습니다.

#### Reddit 무인증 (경로 B)

크리덴셜 없이 특정 서브레딧만 볼 거면 `"subreddit": "worldnews"`처럼 지정하면
Arctic Shift 경로로 인증 없이 수집합니다. (전체 레딧 검색은 경로 A 필요)

### 설정 (`config.json`)

```jsonc
{
  "days_back": 90,                        // 며칠 전까지
  "keywords": ["keyword1", "keyword2"],   // 단어 매칭
  "phrases":  ["an exact sentence"],      // 문장/구문 매칭 (부분 문자열)
  "sources": {
    "reddit":     { "enabled": true, "limit_per_query": 300, "subreddit": null,
                    "client_id": "", "client_secret": "" },
    "hackernews": { "enabled": true, "limit_per_query": 300 },
    "googlenews": { "enabled": true, "hl": "en-US", "gl": "US", "ceid": "US:en" }
  },
  "match_mode": "any",
  "request_delay_sec": 1.0,               // 소스별 요청 간 대기
  "output_dir": "output"
}
```

- **keywords vs phrases**: 각 키워드/문장이 소스에 개별 검색어로 들어가고, 수집 후 제목+본문에서
  다시 매칭해 `matched_keywords` / `matched_phrases` 컬럼에 무엇이 걸렸는지 기록합니다. 대소문자 무시 부분 일치.
- 한국어 뉴스가 필요하면 `googlenews`를 `"hl": "ko", "gl": "KR", "ceid": "KR:ko"`로.

### 출력

`output/crawl_<timestamp>.jsonl`(원문 손실 없음)과 `.csv`(엑셀용, UTF-8 BOM). 공통 스키마는 위 English 표와 동일합니다.

### 다음 단계 (원문 → 분석)

- **키워드 빈도 / 시간별 추이**: `created_utc`로 일자 버킷 + `matched_keywords` 카운트.
- **감성 분석**: `title + text`를 문장 단위로 쪼개 감성 모델에 투입 (영어 `vaderSentiment`, 한국어 `Kiwi`/`KoNLPy`).
- **뉴스 본문 전체 추출**: Google News는 요약만 주므로 `url`을 `newspaper4k`로 넘기면 기사 전문 확보.

---

## References / 참고

- Reddit scrapers 2026: https://dev.to/benthepythondev/the-7-best-reddit-scrapers-in-2026-free-paid-tested-32nb
- Pushshift alternatives (Arctic Shift / PullPush): https://www.redditapis.com/blogs/best-pushshift-alternatives-2026
- News crawler comparison: https://github.com/free-news-api/news-crawlers

## License

MIT
