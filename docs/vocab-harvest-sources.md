# Period vocabulary harvest sources — verified NDL holdings

Manuals, dictionaries, and reference works digitized in the NDL Digital
Collections whose text can be harvested to build the period-correct military
lexicon (kyūjitai, 候文 formulae, rank/unit/tactical terminology) used for OCR
correction and vision-LLM prompting — the "cheap exploitation" path from
`docs/spikes/spike-e-handwriting-htr.md` §4.

All PIDs verified 31 Jul 2026 via the NDL Search API and per-item record pages.
インターネット公開 = internet-public; 図書館・個人送信 = library/registered-user
transmission only. ✚text = NDL's own OCR fulltext exists (retrievable via the
`fulltext-json` path already used by `scripts/ndl_fulltext_pull.ps1` — no
re-OCR needed).

## 1. Military correspondence / formulae manuals (文範)

| Title | Year | PID | Access | Vocab value |
|---|---|---|---|---|
| 軍隊文範 : 兵卒須知 (和田恒彦編, 鍾美堂) | 1907 | 864612 | 公開 ✚text | 候文 letter closings, 祝吊/戦時 sections, 軍用書式 blanks — direct templates for 陣中日誌 prose |
| 帝国軍人文範 (鶴城散史, 文陽堂) | 1907 | 866310 | 公開 ✚text | Soldier's model letters; 候文 formulae |
| 新体軍人文範 (佐藤鉄郎, 宮本武林堂) | 1908 | 864953 | 公開 ✚text | Later-style (新体) epistolary phrasing |
| 陸海軍人文範 (東海丈夫, 井上一書堂) | 1905 | 865542 | 公開 ✚text | Army+navy correspondence formulae |
| 海軍軍人文範 (海軍兵書協会) | 1908 | 865785 | 公開 ✚text | Navy-side counterpart (secondary) |
| 帝國軍人文範 (文陽堂) | 1910 | 1083825 | 送信 ✚text | Same genre — use 866310 instead |

Not digitized on dl.ndl.go.jp (searched, absent): 軍事文範, 軍事郵便文範,
軍隊に関する手紙の書き方 (2009 柏書房 reprint is print-only), 兵卒文範, 従軍文範.

## 2. Military term dictionaries

| Title | Year | PID | Access | Vocab value |
|---|---|---|---|---|
| 大日本兵語辞典 (原田政右衛門, 成武堂) | 1918 | 986304 | 公開 ✚text | Largest monolingual military dictionary of the era — headword list is the lexicon backbone |
| 兵語新辞典 (大日本教育通信社) | 1928 | 1456040 | 公開 ✚text | Updated Shōwa terms (post-WWI weapons, aviation, gas) |
| 兵語新辞典 (軍事学指針社) | 1929 | 1080575 | 公開 ✚text | Alternate 1929 dictionary — cross-check variant readings |
| 英和陸海軍兵語辞典 (山口造酒, 明誠館) | 1910 | 842832 | 公開 ✚text | E–J pairs disambiguate technical terms |
| 独和兵語辞典 (藤井信吉, 金港堂) | 1911 | 901749 | 公開 ✚text | G–J tactical terminology (IJA doctrine German-derived) |
| 兵語辞典 (佐藤庸也, 日本軍用図書) | 1943 | 1870841 | 送信 ✚text | Late-war; library-only |

Not digitized: 軍語辞典 (standalone), 五十音引軍語辞書, 軍事大辞典 (1990 reprint
only), 帝国陸海軍軍語集.

## 3. Field / combat regulations

| Title | Year | PID | Access | Vocab value |
|---|---|---|---|---|
| 陣中要務令 : 軍令陸第6号 (兵用図書) | 1914 | 906611 | 公開 ✚text | **The** field-service manual in force 1914–1938 — 命令・報告・通報 wording of 1931–33 combat reports |
| 陣中要務令 (兵林館 printing) | 1914 | 941788 | 公開 ✚text | Duplicate printing (backup) |
| 陣中要務令教程 : 昭和三年編纂 (教育総監部) | 1928 | 1465544 | 公開 ✚text | Teaching redaction current at Manchurian-Incident time |
| 戦闘綱要 : 軍令陸第一号 (陸軍省) | 1929 | 1457979 | 公開 ✚text | Combat principles in force during the 1933 Great Wall campaign |
| 戦闘綱要草案 (兵用図書) | 1926 | 917148 | 公開 ✚text | Draft version, variant phrasing |
| 作戦要務令 : 綱領、総則及第1部 第2部 (川流堂) | 1938 | 1439842 | 公開 ✚text | Successor manual (1938–45) |
| 作戦要務令 : 綱領,総則及第1部 (尚兵館) | 1940 | 1438366 | 公開 ✚text | 1940 printing |
| 作戰要務令 第2部 (一二三館) | 1938 | 14470436 | 送信 | Use 1439842 instead |
| 作戦要務令・陣中要務令・戦闘綱要対照研究 第1部/第2部 (成武堂) | 1938 | 1452078 / 1452088 | 公開 ✚text | Old-vs-new cross-concordance — maps 1933-era wording to 1938 wording |
| 歩兵操典 (川流堂) | 1940 | 1446616 | 公開 ✚text | Already processed (NDL passthrough, 31 Jul 2026) |
| 新歩兵操典の研究 上巻 (成武堂) | 1928 | 1129207 | 公開 ✚text | 1928 infantry-drill vocabulary commentary |
| 砲兵操典 : 軍令陸第二号 | 1929 | 1450317 | 公開 ✚text | Artillery terms (火砲・観測・照準) |
| 騎兵操典草案 : 陸普第七一八四号 | 1937 | 1457723 | 公開 ✚text | Cavalry terminology |
| 工兵操典 : 軍令陸第四号 | 1913 | 924052 | 公開 ✚text | Engineer terms (築城・架橋・爆破) |
| 輜重兵操典 (川流堂) | 1910 | 844997 | 公開 ✚text | Transport-corps terms |
| 縮刷典令集 : 索引附 輜重兵科 (兵書刊行会) | 1930 | 1458068 | 公開 ✚text | 輜重兵操典+戦闘綱要+陣中要務令+**軍隊符号** in one indexed volume — very efficient harvest |

## 4. Internal administration

| Title | Year | PID | Access | Vocab value |
|---|---|---|---|---|
| 軍隊内務書 (武揚堂書店) | 1921 | 912570 | 公開 ✚text | Barracks-duty vocabulary (週番・日夕点呼・当番) of the 1920s–30s |
| 軍隊内務書 (川流堂) | 1908 | 843513 | 公開 ✚text | Earlier edition, diachronic check |
| 軍隊内務書 : 新旧対照 (琢磨社) | 1934 | 1456540 | 公開 ✚text | 1934 revision with old/new comparison — ideal for the 1922–36 window |
| 軍隊内務書 : 軍令陸第九號 (尙兵館) | 1938 | 14470442 | 送信 | Library-only |
| 陸軍礼式同附録 : 軍令陸第7号 | 1913 | 924403 | 公開 ✚text | Salute/ceremony vocabulary, rank-address forms |
| 軍人勅諭謹解 (友田宜剛, 琢磨社) | 1934 | 1442476 | 公開 ✚text | Rescript exegesis — kyūjitai moral vocabulary quoted verbatim in diaries |
| 軍隊教授 : 兵卒須知 (養武会) | 1904 | 842975 | 公開 ✚text | Enlisted-man's basic-knowledge phrasing |
| 最新歩兵須知 (川流堂) | 1928 | 1457915 | 公開 ✚text | Shōwa infantry handbook — rank/duty/kit vocabulary |
| 完全歩兵須知 (斎藤市平) | 1933 | 1457724 | 公開 ✚text | Great-Wall-campaign year exactly |
| 最新歩兵須知 (藤谷芳三郎) | 1937 | 1457916 | 公開 ✚text | Late-window edition |

Not digitized as such: 軍隊内務令 (1943; IMTFE exhibit excerpts only — 内務書
covers our window), 陸軍礼式令 (pre-1940 items titled 陸軍礼式, above).

## 5. Officer education texts

| Title | Year | PID | Access | Vocab value |
|---|---|---|---|---|
| 最新戦術学教程 巻上/巻下 (兵書刊行会) | 1927 | 1457767 / 1457021 | 公開 ✚text | Tactics-course prose — the register of 戦闘詳報/講評 lectures |
| 軍制学教程 (教育総監部, 成武堂) | 1928 | 1447175 | 公開 ✚text | Army-organization vocabulary |
| 軍制学教程 (兵用図書) | 1935 | 1080406 | 公開 ✚text | 1935 revision |
| 最新兵器学教程 (兵書刊行会) | 1927 | 1033125 | 公開 ✚text | Weapon nomenclature |
| 兵器学教程 昭和9年改訂 (陸軍士官学校) | 1934 | 1906257 | 公開 ✚text | Actual 陸士 textbook — authoritative weapon terms |
| 臨時築城教程 (陸軍文庫) | 1882 | 844976 | 公開 ✚text | Fortification terms (Meiji only; no 1900–40 築城学教程 digitized — known gap) |

## 6. Penmanship copybooks (glyph exemplars)

| Title | Year | PID | Access | Vocab value |
|---|---|---|---|---|
| 甲種小学書方手本解説 尋3上 (笠井義夫, 明治図書; series 尋1–尋5 = pids 1118442–1440797) | 1933–37 | 1118468 | 公開 ✚text | Shōwa school-hand letterforms the diary writers learned |
| 高等小学書方手本新指導書 高等2年 (東洋図書) | 1934 | 1271864 | 公開 ✚text | Upper-elementary hand — closest to adult soldier handwriting |
| 高等小學書方手本新指導書 高等1年 | 1933 | 1083446 | 送信 ✚text | Library-only variant |

軍人習字帖 does not exist in NDL (0 hits). Shōwa copybooks are titled 書方手本,
not 習字帖.

## 7. Personnel reference

| Title | Year | PID | Access | Vocab value |
|---|---|---|---|---|
| 陸軍現役将校同相当官実役停年名簿 大正9年調 | 1920 | 930893 | 公開 ✚text | Core corpus (already in worklist) |
| 同 大正14年9月1日調 | 1925 | 1908495 | 公開 ✚text | " |
| 同 昭和2年9月1日調 | 1927 | 1454434 | 公開 ✚text | " |
| 同 昭和5年9月1日調 | 1930 | 1454436 | 公開 ✚text | " |
| 同 : 索引付 昭和8年9月1日調 | 1933 | 1449426 | 公開 ✚text | Campaign-year volume, with surname index |
| 同 昭和11年9月1日調 | 1936 | 1454447 | 公開 ✚text | End of project window |
| 職員録 昭和8年1月1日現在 (印刷局) | 1933 | 1447944 | 公開 ✚text | Government-wide office/position titles |
| 職員録 昭和11年1月1日現在 (印刷局) | 1936 | 1452201 | 公開 ✚text | Annual series 1930–37 all internet-public |

## Harvest priority (top 5)

1. **陣中要務令 1914 (pid 906611)** — the manual in force for every 1931–33
   combat report; 命令・報告・通報 formulae and 斥候/宿営/行軍 vocabulary come
   straight from it. Highest overlap with the handwritten corpus.
2. **大日本兵語辞典 1918 (pid 986304)** — the headword list alone bootstraps the
   military lexicon; definitions supply collocations for OCR language-model
   correction.
3. **縮刷典令集 輜重兵科 1930 (pid 1458068)** — three doctrine texts plus 軍隊符号
   (unit-symbol abbreviations) in one indexed volume; single cheap harvest.
4. **軍隊文範 : 兵卒須知 1907 (pid 864612)** — the only digitized 軍隊文範; sole
   source for 候文 closings and 軍用書式 blank-form phrasing dominating the diaries.
5. **停年名簿 昭和8年・索引付 1933 (pid 1449426)** — feeds the name/rank/unit
   gazetteer for the campaign years (with the 1925–36 run for temporal coverage).

Every インターネット公開 row carries NDL's fulltext flag, so harvesting is a
`ndl_fulltext_pull.ps1`-style pull, not an OCR job. The 送信 items are all
substitutable by internet-public equivalents listed alongside them.
