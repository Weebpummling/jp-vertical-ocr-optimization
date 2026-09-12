# Decision: Taishō roster field labels

Lead's decisions, 11 Sep 2026, on the four templates `taisho12-teinen-meibo-wide/-narrow`
(pid 930894, 大正12年9月1日調) and `taisho15-teinen-meibo-wide/-narrow` (pid 1908494,
大正15年9月1日調). Band names come from the legend column the volumes print at the head of
each 尉官 section (frames 250 and 350 of both). All fields now carry `confirmed: true`.

| Band | Printed legend | Field | Decision |
|---|---|---|---|
| top | 現官ノ實役停年 | `service_in_rank` | confirmed; 年、月、日 of service, not a date |
| 2 | 列次 | `seniority_no` | confirmed; the circled mark before some numbers (⊖1505) is noted in 備考, meaning open |
| 3 | 任官ノ年月日 | `appointment_dates` | confirmed; the line tagged 少尉 in the cell **is** the schema's `commissioning_date` and is typed into the form's 任官年月日; the cell stays unmapped |
| 4 (1926 only) | 出身期別 | `cohort` | confirmed; plain number = 陸軍士官学校 class; `N少` = class N of a different commissioning route (e.g. 少尉候補者); record as printed |
| 5 | 職名（1926: 職名、命課ノ年月日） | `post` | confirmed |
| 6 | 本邦位、勳、功、爵、學位・外國勳章 | `court_rank_decorations` | confirmed |
| 7 | 氏名 ＋ 年齡 | `name_raw` | confirmed; the small figures are the **age** at the 調 date (年、月), not a birth date |

Evidence for the age reading: 引田乾作 reads 五一、一〇 in the 1923 volume (frame 20) and
五四、一〇 in the 1926 volume (frame 20) - three years apart to the month; no era mark is
printed, where the Shōwa volumes print one (明三〇、七、六). The worksheet column is labelled
生年月日・年齡 and holds the figures as read on either edition.

Not decided here: what the circled seniority mark denotes; the 各部 sections (no 列次 row),
休職 and the index, which no template covers.
