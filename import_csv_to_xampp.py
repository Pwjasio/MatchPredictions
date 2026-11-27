#!/usr/bin/env python3
"""
Opcjonalny importer lokalnych plików matches.csv oraz matches-bet.csv do MySQL (XAMPP).
"""
import os
from datetime import datetime
import numpy as np
import pandas as pd
from app import app, db, Match, Odds, normalize_team

MATCHES_CSV = "matches.csv"
ODDS_CSV = "matches-bet.csv"

def infer_season(dt):
    if pd.isna(dt):
        return "2526"
    y = dt.year % 100
    if dt.month >= 7:
        return f"{y:02d}{(y+1):02d}"
    return f"{(y-1):02d}{y:02d}"

def run_import():
    with app.app_context():
        db.create_all()
        if os.path.exists(MATCHES_CSV):
            df = pd.read_csv(MATCHES_CSV, low_memory=False)
            df.columns = [c.strip() for c in df.columns]
            date_col = next((c for c in df.columns if 'date' in c.lower()), None)
            df['__date'] = pd.to_datetime(df[date_col], errors='coerce') if date_col else datetime.utcnow()

            div_col = next((c for c in df.columns if c.lower() in ('division', 'div', 'league', 'competition')), None)
            if div_col:
                filtered = df[df[div_col].astype(str).str.lower().str.contains('sp1|primera|la liga|laliga', na=False)]
                if not filtered.empty:
                    df = filtered

            h_col = next((c for c in df.columns if c.lower() in ('hometeam', 'home_team', 'home')), None)
            a_col = next((c for c in df.columns if c.lower() in ('awayteam', 'away_team', 'away')), None)
            hg_col = next((c for c in df.columns if c in ('FTHome', 'FTHG')), None)
            ag_col = next((c for c in df.columns if c in ('FTAway', 'FTAG')), None)

            if h_col and a_col and hg_col and ag_col:
                df = df.dropna(subset=[hg_col, ag_col])
                Match.query.delete()

                def get_num(row, cols):
                    for col in cols:
                        if col in row.index and pd.notna(row[col]):
                            try: return float(row[col])
                            except Exception: pass
                    return None

                records = []
                for _, row in df.iterrows():
                    h_raw = str(row[h_col]).strip()
                    a_raw = str(row[a_col]).strip()
                    dt = row['__date']
                    records.append(Match(
                        division='SP1',
                        season=infer_season(dt),
                        match_date=dt.to_pydatetime() if pd.notna(dt) else None,
                        home_team=h_raw,
                        away_team=a_raw,
                        home_norm=normalize_team(h_raw),
                        away_norm=normalize_team(a_raw),
                        ft_home=int(row[hg_col]),
                        ft_away=int(row[ag_col]),
                        home_shots=get_num(row, ['HomeShots', 'HS']),
                        away_shots=get_num(row, ['AwayShots', 'AS']),
                        home_target=get_num(row, ['HomeTarget', 'HST']),
                        away_target=get_num(row, ['AwayTarget', 'AST']),
                        home_corners=get_num(row, ['HomeCorners', 'HC']),
                        away_corners=get_num(row, ['AwayCorners', 'AC']),
                        home_yellow=get_num(row, ['HomeYellow', 'HY']),
                        away_yellow=get_num(row, ['AwayYellow', 'AY']),
                        home_red=get_num(row, ['HomeRed', 'HR']),
                        away_red=get_num(row, ['AwayRed', 'AR']),
                        home_elo=get_num(row, ['HomeElo', 'HomeELO']),
                        away_elo=get_num(row, ['AwayElo', 'AwayELO']),
                    ))
                db.session.bulk_save_objects(records)
                db.session.commit()
                print(f"Zaimportowano {len(records)} meczów.")

        if os.path.exists(ODDS_CSV):
            df_o = pd.read_csv(ODDS_CSV, low_memory=False)
            df_o.columns = [c.strip() for c in df_o.columns]
            date_col = next((c for c in df_o.columns if 'date' in c.lower()), None)
            df_o['__date'] = pd.to_datetime(df_o[date_col], dayfirst=True, errors='coerce') if date_col else datetime.utcnow()
            h_col = next((c for c in df_o.columns if c.lower() in ('hometeam', 'home_team', 'home')), None)
            a_col = next((c for c in df_o.columns if c.lower() in ('awayteam', 'away_team', 'away')), None)
            if h_col and a_col:
                Odds.query.delete()
                odds_records = []
                for _, row in df_o.iterrows():
                    avg_h = pd.to_numeric(row.get('AvgH', row.get('AvgHome', np.nan)), errors='coerce')
                    avg_d = pd.to_numeric(row.get('AvgD', row.get('AvgDraw', np.nan)), errors='coerce')
                    avg_a = pd.to_numeric(row.get('AvgA', row.get('AvgAway', np.nan)), errors='coerce')
                    odds_records.append(Odds(
                        match_date=row['__date'].to_pydatetime() if pd.notna(row['__date']) else None,
                        home_norm=normalize_team(str(row[h_col])),
                        away_norm=normalize_team(str(row[a_col])),
                        avg_home=float(avg_h) if pd.notna(avg_h) else None,
                        avg_draw=float(avg_d) if pd.notna(avg_d) else None,
                        avg_away=float(avg_a) if pd.notna(avg_a) else None,
                    ))
                db.session.bulk_save_objects(odds_records)
                db.session.commit()
                print(f"Zaimportowano {len(odds_records)} kursów.")

if __name__ == "__main__":
    run_import()
