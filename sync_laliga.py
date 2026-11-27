#!/usr/bin/env python3
"""
Pobiera aktualny sezon LaLiga (SP1) z football-data.co.uk + Elo z api.clubelo.com
i aktualizuje bazę MySQL w XAMPP (laliga_predictor).
"""
import io
from datetime import datetime
import requests
import numpy as np
import pandas as pd
from app import app, db, Match, Odds, normalize_team

CURRENT_SEASON = "2627"  # Sezon 2026/27
CSV_URL = f"https://www.football-data.co.uk/mmz4281/{CURRENT_SEASON}/SP1.csv"

def fetch_club_elo_map():
    """Pobiera aktualne punkty Elo klubów z api.clubelo.com."""
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    url = f"http://api.clubelo.com/{today_str}"
    elo_map = {}
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            df_elo = pd.read_csv(io.StringIO(resp.text))
            for _, r in df_elo.iterrows():
                club = normalize_team(str(r.get('Club', '')))
                elo = pd.to_numeric(r.get('Elo', np.nan), errors='coerce')
                if club and pd.notna(elo):
                    elo_map[club] = float(elo)
    except Exception as e:
        print(f"Ostrzeżenie: nie udało się pobrać Elo z ClubElo ({e}).")
    return elo_map

def sync_from_web(season_code=CURRENT_SEASON):
    url = f"https://www.football-data.co.uk/mmz4281/{season_code}/SP1.csv"
    print(f"Pobieranie danych LaLiga z: {url} ...")
    df = pd.read_csv(url)
    df = df.dropna(subset=['HomeTeam', 'AwayTeam', 'FTHG', 'FTAG'])
    df['__date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')

    elo_map = fetch_club_elo_map()
    added_matches = 0
    added_odds = 0

    with app.app_context():
        db.create_all()
        for _, row in df.iterrows():
            m_date = row['__date'].to_pydatetime() if pd.notna(row['__date']) else None
            h_raw = str(row['HomeTeam']).strip()
            a_raw = str(row['AwayTeam']).strip()
            h_norm = normalize_team(h_raw)
            a_norm = normalize_team(a_raw)

            exists = Match.query.filter_by(
                home_norm=h_norm,
                away_norm=a_norm,
                match_date=m_date
            ).first()

            if not exists:
                def val(col):
                    v = pd.to_numeric(row.get(col, np.nan), errors='coerce')
                    return float(v) if pd.notna(v) else None

                db.session.add(Match(
                    division='SP1',
                    season=season_code,
                    match_date=m_date,
                    home_team=h_raw,
                    away_team=a_raw,
                    home_norm=h_norm,
                    away_norm=a_norm,
                    ft_home=int(row['FTHG']),
                    ft_away=int(row['FTAG']),
                    home_shots=val('HS'),
                    away_shots=val('AS'),
                    home_target=val('HST'),
                    away_target=val('AST'),
                    home_corners=val('HC'),
                    away_corners=val('AC'),
                    home_yellow=val('HY'),
                    away_yellow=val('AY'),
                    home_red=val('HR'),
                    away_red=val('AR'),
                    home_elo=elo_map.get(h_norm),
                    away_elo=elo_map.get(a_norm),
                ))
                added_matches += 1

            avg_h = pd.to_numeric(row.get('AvgH', np.nan), errors='coerce')
            avg_d = pd.to_numeric(row.get('AvgD', np.nan), errors='coerce')
            avg_a = pd.to_numeric(row.get('AvgA', np.nan), errors='coerce')

            if pd.notna(avg_h) and pd.notna(avg_a):
                odd_exists = Odds.query.filter_by(
                    home_norm=h_norm,
                    away_norm=a_norm,
                    match_date=m_date
                ).first()
                if not odd_exists:
                    db.session.add(Odds(
                        match_date=m_date,
                        home_norm=h_norm,
                        away_norm=a_norm,
                        avg_home=float(avg_h),
                        avg_draw=float(avg_d) if pd.notna(avg_d) else None,
                        avg_away=float(avg_a)
                    ))
                    added_odds += 1

        db.session.commit()
    return {'added_matches': added_matches, 'added_odds': added_odds}

if __name__ == "__main__":
    res = sync_from_web()
    print(f"Gotowe! Dodano {res['added_matches']} meczów i {res['added_odds']} kursów.")
