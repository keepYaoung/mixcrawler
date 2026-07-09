# mixcrawler

> Multi-source last-90-days crawler — **Reddit + Hacker News + Google News**, searchable by **keywords and full phrases**.
> 여러 소스(**Reddit + Hacker News + Google News**)에서 지난 N일(기본 90일)치 원문을 **키워드와 문장(구문) 둘 다로** 수집합니다.

Saves raw results loss-less to `JSONL` and spreadsheet-friendly `CSV`. Only dependency: `requests`.
원문을 손실 없이 `JSONL`, 엑셀용 `CSV`로 저장. 의존성은 `requests` 하나뿐.

```bash
python3 -m pip install requests
python3 crawler.py          # reads config.json / config.json 사용
```

---

## English

### Source reality (2026, actually tested)

| Source | Auth | Last 90 days | Note |
|--------|------|--------------|------|
| **Reddit — single subreddit** | **none** ✅ | ✅ | via Arctic Shift archive (posts **+ comments**) |
| **Reddit — all of reddit** | OAuth (gated) | ⚠️ | self-serve API keys were **discontinued**; needs manual approval |
| **Hacker News** (Algolia API) | none | ✅ | works out of the box |
| **Google News** (RSS `when:90d`) | none | ✅ | works out of the box |

> **Reddit in 2026:** unauthenticated `reddit.com/.json` returns **403**, and creating an
> API app is no longer self-serve (Reddit's *Responsible Builder Policy* → manual approval).
> **So this tool defaults to the no-auth path:** if you set a single `subreddit`, it pulls the
> **entire subreddit for the window** from the free **Arctic Shift** archive (Pushshift successor),
> including **comments** — then filters locally by your keywords/phrases.

### How the Reddit no-auth mode works

- Set `"subreddit": "PTE"` (no credentials needed).
- It pulls **all posts and comments** in the last N days, **newest-first**.
  If `limit_per_query` is hit, you keep the **most recent** items and only older ones drop —
  ideal for "recent trends". Raise `limit_per_query` to go deeper into history.
- Comments matter: advice from high-scorers lives in comments, so `include_comments: true`.
- Your `keywords`/`phrases` become **local filters** here (tagged in `matched_keywords`
  / `matched_phrases`), so you can re-slice the saved data without re-crawling.

### Optional: all-of-reddit search (OAuth)

If you get Reddit API approval, create a **script** app at https://www.reddit.com/prefs/apps
and put `client_id` / `client_secret` into `config.json`. The crawler then searches all of
reddit per keyword via `oauth.reddit.com` (no PRAW needed). Leave them blank to use the
no-auth subreddit path above.

### Output

`output/crawl_<timestamp>.jsonl` (loss-less) and `.csv` (Excel, UTF-8 BOM). Common schema:

```
source, id, created_utc(ISO8601 UTC), title, text, url, author,
score, subreddit, query, matched_keywords, matched_phrases
```

`source` is `reddit` (post), `reddit_comment`, `hackernews`, or `googlenews`.
Same columns across sources → uniform downstream analysis. Sort by `score` to find the
most-upvoted (high-scorer) advice.

### Next steps (raw → analysis)

- **Keyword frequency / time trends**: bucket by `created_utc`, count `matched_keywords`.
- **Sentiment**: split `title + text` into sentences → sentiment model (`vaderSentiment` EN, `Kiwi`/`KoNLPy` KO).
- **Chinese-speaking cohort**: filter records containing CJK characters (`[一-鿿]`).

---

## 한국어

### 소스별 현실 (2026년 기준, 실제 테스트함)

| 소스 | 인증 | 지난 90일 | 비고 |
|------|------|-----------|------|
| **Reddit — 단일 서브레딧** | **불필요** ✅ | ✅ | Arctic Shift 아카이브로 글 **+ 댓글** 수집 |
| **Reddit — 전체 레딧** | OAuth (승인제) | ⚠️ | 셀프서비스 API 키 발급 **폐지**, 수동 승인 필요 |
| **Hacker News** (Algolia API) | 불필요 | ✅ | 바로 됨 |
| **Google News** (RSS `when:90d`) | 불필요 | ✅ | 바로 됨 |

> **2026년 레딧 현실:** 무인증 `reddit.com/.json`은 **403**, API 앱 생성도 더 이상
> 셀프서비스가 아님(레딧 *Responsible Builder Policy* → 수동 승인).
> **그래서 이 도구는 무인증 경로를 기본으로 씁니다:** `subreddit` 하나만 지정하면
> 무료 **Arctic Shift** 아카이브(Pushshift 후속)에서 **해당 서브레딧 전체(댓글 포함)**를
> 기간만큼 긁어와 **로컬에서 키워드/문장으로 필터**합니다.

### Reddit 무인증 모드 동작 방식

- `"subreddit": "PTE"`만 지정 (크리덴셜 불필요).
- 지난 N일치 **글+댓글을 최신순으로** 수집. `limit_per_query`에 걸리면 **최근 것부터**
  남고 오래된 것만 잘림 → **최근 경향** 분석에 최적. 과거를 더 보려면 `limit_per_query`를 올리면 됨.
- **댓글이 핵심**: 고득점자 조언은 댓글에 있으므로 `include_comments: true`.
- `keywords`/`phrases`는 여기선 **로컬 필터**로 작동(`matched_keywords`/`matched_phrases`에 태그).
  저장된 데이터를 재크롤 없이 아무 키워드로나 다시 슬라이스 가능.

### 선택: 전체 레딧 검색 (OAuth)

레딧 API 승인을 받았다면 https://www.reddit.com/prefs/apps 에서 **script** 앱을 만들고
`client_id`/`client_secret`을 `config.json`에 넣으면 됩니다. 그러면 `oauth.reddit.com`으로
키워드별 전체 레딧 검색을 합니다(PRAW 불필요). 비워두면 위 무인증 서브레딧 경로 사용.

### 설정 (`config.json`)

```jsonc
{
  "days_back": 90,
  "keywords": ["template", "79", "essay"],   // 단어 = 소스 질의(OAuth/뉴스) + 로컬 태그
  "phrases":  ["do not overcomplicate"],      // 문장/구문 = 로컬 부분일치 태그
  "sources": {
    "reddit":     { "enabled": true, "subreddit": "PTE", "include_comments": true,
                    "limit_per_query": 1500, "client_id": "", "client_secret": "" },
    "hackernews": { "enabled": false, "limit_per_query": 300 },
    "googlenews": { "enabled": true, "hl": "en-US", "gl": "US", "ceid": "US:en" }
  },
  "request_delay_sec": 0.5,
  "output_dir": "output"
}
```
- 한국어 뉴스가 필요하면 `googlenews`를 `"hl":"ko","gl":"KR","ceid":"KR:ko"`로.

### 출력

`output/crawl_<시각>.jsonl`(원문 손실 없음) + `.csv`(엑셀, UTF-8 BOM). 스키마는 위 English와 동일.
`score`로 정렬하면 가장 많이 추천받은(고득점자) 조언을 찾을 수 있습니다.

### 다음 단계 (원문 → 분석)

- **키워드 빈도/시간 추이**: `created_utc` 일자 버킷 + `matched_keywords` 카운트.
- **감성 분석**: `title + text`를 문장 단위로 → 감성 모델(영어 `vaderSentiment`, 한국어 `Kiwi`/`KoNLPy`).
- **중국어권 코호트**: CJK 문자(`[一-鿿]`) 포함 레코드만 필터.

---

## References / 참고

- Reddit Responsible Builder Policy: https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy
- Arctic Shift (Pushshift 후속): https://github.com/ArthurHeitmann/arctic_shift
- Pushshift 대안 비교: https://www.redditapis.com/blogs/best-pushshift-alternatives-2026

## License

MIT
