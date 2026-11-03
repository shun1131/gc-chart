# GC Chart

## 基本ルール
- 返答は常に日本語で行ってください。

## 概要
仮想通貨の「GC比率」と BTC/ETH 価格などを重ねて見る個人用チャート。利用者は旦那1人。
- 公開: GitHub Pages(public repo shun1131/gc-chart。noindex 指定、URLを知っている人だけが見る想定)
- 更新: GitHub Actions `daily.yml` が毎日 09:30 JST にデータを作り直して Pages へデプロイ
- 60日無活動で定期実行が止まる対策: 同ワークフローの keepalive ジョブが、最終コミットから45日たったら空コミットを push する

## 指標の定義
- **rate USD**: 対象銘柄のうち USDT建て終値で「短期SMA > 長期SMA」の銘柄の割合
- **rate BTC**: 各銘柄の終値 ÷ BTCUSDT の終値(BTC建て価格)で同じ判定をした割合
- 対象銘柄: Binance現物 USDTペアの24h出来高上位100(ステーブル・ラップ系は `EXCLUDE` で除外)。
  現在上場中の銘柄だけなので、昔ほど母数が少ない(2024年は50前後)。1日の母数が10未満の日は値なし
- 期間の組み合わせ: `PERIOD_PAIRS`(7/25, 5/20, 10/30, 25/75)。画面のプルダウンで切り替える
- 補助系列: BTCUSD, ETHUSD(Binance)、恐怖指数(alternative.me Fear & Greed ÷100)、RUT2000・SP600(Yahoo、休場日は前日値で埋める)

## シグナル表示(画面上で判定)
- ▲底反転: 直近15日に rate USD が 0.1 を割ったあと 0.2 を上抜けた日
- ▼天井崩れ: 直近15日に 0.9 を超えたあと 0.8 を下抜けた日
- 判定条件は `site/index.html` の `SIGNAL` 定数。選択中の短期・長期の組み合わせで判定する
- 2026-11-03 検証メモ(BTC 30日後、2022/9〜): 底反転は条件を変えても全期間の平均より良い(+4.5〜8% / 基準+3.9%)。
  天井崩れは 0.9→0.8 のときだけ効く(-1.4%)ので条件の変更に弱い。どちらも相場の地合い(年)で成績が大きく変わる

## 構成
- `src/build_data.py` — 取得と計算(標準ライブラリのみ)。出力 `site/data.json`(gitignore対象、毎回作り直す)
- `site/index.html` — ApexCharts の表示ページ

## ローカル確認
```bash
SSL_CERT_FILE=$(python3 -c "import certifi;print(certifi.where())") python3 src/build_data.py
cd site && python3 -m http.server 8765   # http://localhost:8765/
```
(Mac の python.org版Pythonは証明書が未設定なので SSL_CERT_FILE を渡す)

## 経緯
- 2026-11-03 旦那の参考画像(凡例: rate BTC / rate USD / BTCUSD / ETHUSD / RUT2000 / SP600)から再現。
  元サイトの母集団は不明。山谷の時期は一致、高さは数%〜20%ほどずれる日がある
