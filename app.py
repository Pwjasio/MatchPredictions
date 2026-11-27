#!/usr/bin/env python3
import os
import difflib
from datetime import datetime
import numpy as np
from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy

# ---------- KONFIGURACJA SILNIKA I BAZY SUPABASE ----------
SUPABASE_URI = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.lcwjjksfowvgdmbxdqvf:BZV4Ner9BlaM@aws-0-eu-central-1.pooler.supabase.com:5432/postgres?sslmode=require"
)

# SQLAlchemy 2.0 wymaga prefiksu postgresql:// zamiast postgres://
if SUPABASE_URI.startswith("postgres://"):
    SUPABASE_URI = SUPABASE_URI.replace("postgres://", "postgresql://", 1)

CURRENT_SEASON = "2627"  # Aktualny sezon (2026/27)

SIMULATIONS = 100_000
SEASON_SIMULATIONS = 5_000  # Symulacje całego sezonu do tabeli końcowej
DECAY_DAYS = 365 * 2.5
ELO_COEF = 0.0012
MARKET_BLEND = 0.12
HOME_ADV = 0.18

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = SUPABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
}

db = SQLAlchemy(app)

# ------------------ MODELE POSTGRESQL (SUPABASE) ------------------

class Match(db.Model):
    __tablename__ = 'matches'
    id = db.Column(db.Integer, primary_key=True)
    division = db.Column(db.String(50), default='SP1')
    season = db.Column(db.String(10), default=CURRENT_SEASON, index=True)
    match_date = db.Column(db.DateTime)
    home_team = db.Column(db.String(100), nullable=False)
    away_team = db.Column(db.String(100), nullable=False)
    home_norm = db.Column(db.String(100), index=True)
    away_norm = db.Column(db.String(100), index=True)
    ft_home = db.Column(db.Integer)
    ft_away = db.Column(db.Integer)
    home_shots = db.Column(db.Float)
    away_shots = db.Column(db.Float)
    home_target = db.Column(db.Float)
    away_target = db.Column(db.Float)
    home_corners = db.Column(db.Float)
    away_corners = db.Column(db.Float)
    home_yellow = db.Column(db.Float)
    away_yellow = db.Column(db.Float)
    home_red = db.Column(db.Float)
    away_red = db.Column(db.Float)
    home_elo = db.Column(db.Float)
    away_elo = db.Column(db.Float)

class Odds(db.Model):
    __tablename__ = 'odds'
    id = db.Column(db.Integer, primary_key=True)
    match_date = db.Column(db.DateTime)
    home_norm = db.Column(db.String(100), index=True)
    away_norm = db.Column(db.String(100), index=True)
    avg_home = db.Column(db.Float)
    avg_draw = db.Column(db.Float)
    avg_away = db.Column(db.Float)

# Tworzymy tabele po zdefiniowaniu klas Match i Odds
with app.app_context():
    db.create_all()

# ------------------ POMOCNICZE ------------------

def normalize_team(name: str) -> str:
    if not isinstance(name, str):
        return ""
    s = name.lower()
    for token in ('fc ', 'fc.', 'cf ', 'cf.', 'club ', 'club.', 'team ', 'team.'):
        s = s.replace(token, ' ')
    s = s.replace('.', '').replace('-', ' ').replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
    s = ' '.join(s.split())
    return ''.join(ch for ch in s if ch.isalnum() or ch.isspace()).strip()

def get_canonical_teams():
    rows = db.session.query(Match.home_norm, Match.home_team).distinct().all()
    mapping = {}
    for norm, raw in rows:
        if norm and norm not in mapping:
            mapping[norm] = raw
    return mapping

def find_team_candidate(query: str, team_map: dict):
    qn = normalize_team(query)
    if not qn:
        return None
    if qn in team_map:
        return qn
    for t in team_map.keys():
        if qn in t or t in qn:
            return t
    matches = difflib.get_close_matches(qn, list(team_map.keys()), n=1, cutoff=0.6)
    return matches[0] if matches else None

# ------------------ SILNIK PREDYKCJI MECZU ------------------

def weighted_moments(values, weights):
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    mask = (~np.isnan(values)) & (weights > 0)
    if mask.sum() == 0:
        return np.nan, np.nan
    v, w = values[mask], weights[mask]
    mean = np.sum(w * v) / np.sum(w)
    var = np.sum(w * (v - mean) ** 2) / np.sum(w)
    return mean, var

def compute_time_weights(dates, today):
    days = np.array([(today - d).days if d is not None else 99999 for d in dates])
    days = np.clip(days, 0, None)
    return np.exp(-days / DECAY_DAYS)

def estimate_team_stats(home_norm: str, away_norm: str):
    today = datetime.utcnow()
    home_matches = Match.query.filter_by(home_norm=home_norm).all()
    away_matches = Match.query.filter_by(away_norm=away_norm).all()

    wh = compute_time_weights([m.match_date for m in home_matches], today) if home_matches else np.array([])
    wa = compute_time_weights([m.match_date for m in away_matches], today) if away_matches else np.array([])

    mean_h, var_h = weighted_moments([m.ft_home for m in home_matches], wh) if home_matches else (1.35, 1.4)
    mean_a, var_a = weighted_moments([m.ft_away for m in away_matches], wa) if away_matches else (1.05, 1.1)

    if np.isnan(mean_h) or mean_h <= 0: mean_h = 1.35
    if np.isnan(mean_a) or mean_a <= 0: mean_a = 1.05
    if np.isnan(var_h) or var_h <= 0: var_h = max(1.0, mean_h * 1.2)
    if np.isnan(var_a) or var_a <= 0: var_a = max(1.0, mean_a * 1.2)

    last_h = Match.query.filter(Match.home_norm == home_norm, Match.home_elo.isnot(None)).order_by(Match.match_date.desc()).first()
    last_a = Match.query.filter(Match.away_norm == away_norm, Match.away_elo.isnot(None)).order_by(Match.match_date.desc()).first()
    elo_diff = (last_h.home_elo - last_a.away_elo) if (last_h and last_a) else 0.0

    market_factor = 0.0
    last_odd = Odds.query.filter_by(home_norm=home_norm, away_norm=away_norm).order_by(Odds.match_date.desc()).first()
    if last_odd and last_odd.avg_home and last_odd.avg_away and last_odd.avg_home > 1 and last_odd.avg_away > 1:
        market_factor = (1.0 / last_odd.avg_home) - (1.0 / last_odd.avg_away)

    log_lh = np.log(max(0.05, mean_h)) + HOME_ADV + ELO_COEF * elo_diff + MARKET_BLEND * market_factor
    log_la = np.log(max(0.05, mean_a)) - ELO_COEF * elo_diff - MARKET_BLEND * market_factor

    lambda_home = float(np.exp(log_lh))
    lambda_away = float(np.exp(log_la))

    def moments_to_nb(mean, var):
        if var <= mean + 1e-6:
            return None
        r = (mean * mean) / (var - mean)
        return (r, r / (r + mean)) if r > 0 else None

    def get_weighted_stat(matches_list, weights, attr_name, default):
        vals = [getattr(m, attr_name) for m in matches_list if getattr(m, attr_name) is not None]
        w_sub = [w for m, w in zip(matches_list, weights) if getattr(m, attr_name) is not None]
        if vals and sum(w_sub) > 0:
            return float(np.average(vals, weights=w_sub))
        return float(default)

    return {
        'lambda_home': lambda_home,
        'lambda_away': lambda_away,
        'nb_home': moments_to_nb(mean_h, var_h),
        'nb_away': moments_to_nb(mean_a, var_a),
        'shots_home': get_weighted_stat(home_matches, wh, 'home_shots', 11.0),
        'shots_away': get_weighted_stat(away_matches, wa, 'away_shots', 9.2),
        'target_home': get_weighted_stat(home_matches, wh, 'home_target', 4.5),
        'target_away': get_weighted_stat(away_matches, wa, 'away_target', 3.6),
        'corners_home': get_weighted_stat(home_matches, wh, 'home_corners', 4.8),
        'corners_away': get_weighted_stat(away_matches, wa, 'away_corners', 3.9),
        'yellow_home': get_weighted_stat(home_matches, wh, 'home_yellow', 2.1),
        'yellow_away': get_weighted_stat(away_matches, wa, 'away_yellow', 2.3),
        'red_home': get_weighted_stat(home_matches, wh, 'home_red', 0.08),
        'red_away': get_weighted_stat(away_matches, wa, 'away_red', 0.09),
    }

def simulate_match_forecast(home_norm: str, away_norm: str, simulations=SIMULATIONS):
    est = estimate_team_stats(home_norm, away_norm)
    rng = np.random.default_rng()

    if est['nb_home']:
        r_h, p_h = est['nb_home']
        home_goals = rng.negative_binomial(n=max(1, int(round(r_h))), p=np.clip(p_h, 1e-6, 1 - 1e-6), size=simulations)
    else:
        home_goals = rng.poisson(lam=est['lambda_home'], size=simulations)

    if est['nb_away']:
        r_a, p_a = est['nb_away']
        away_goals = rng.negative_binomial(n=max(1, int(round(r_a))), p=np.clip(p_a, 1e-6, 1 - 1e-6), size=simulations)
    else:
        away_goals = rng.poisson(lam=est['lambda_away'], size=simulations)

    home_goals += ((rng.random(simulations) < 0.04) & (rng.random(simulations) < 0.75)).astype(int)
    away_goals += ((rng.random(simulations) < 0.04) & (rng.random(simulations) < 0.75)).astype(int)

    red_h = rng.poisson(lam=est['red_home'], size=simulations) > 0
    red_a = rng.poisson(lam=est['red_away'], size=simulations) > 0
    home_goals = np.clip(home_goals - (red_h & (rng.random(simulations) < 0.5)).astype(int), 0, None)
    away_goals = np.clip(away_goals - (red_a & (rng.random(simulations) < 0.5)).astype(int), 0, None)

    pairs = home_goals.astype(np.int32) * 100 + away_goals.astype(np.int32)
    unique, counts = np.unique(pairs, return_counts=True)
    freq = sorted(zip(unique.tolist(), counts.tolist()), key=lambda x: x[1], reverse=True)

    top10 = [{'home': int(c // 100), 'away': int(c % 100), 'prob': round(cnt / simulations * 100.0, 2)} for c, cnt in freq[:10]]

    wins_h = float(np.sum(home_goals > away_goals) / simulations * 100.0)
    draws = float(np.sum(home_goals == away_goals) / simulations * 100.0)
    wins_a = float(np.sum(home_goals < away_goals) / simulations * 100.0)
    btts = float(np.sum((home_goals > 0) & (away_goals > 0)) / simulations * 100.0)
    over25 = float(np.sum((home_goals + away_goals) > 2.5) / simulations * 100.0)

    stats = {
        'prob_home': round(wins_h, 1),
        'prob_draw': round(draws, 1),
        'prob_away': round(wins_a, 1),
        'btts': round(btts, 1),
        'over_2_5': round(over25, 1),
        'lambda_home': round(est['lambda_home'], 2),
        'lambda_away': round(est['lambda_away'], 2),
        'shots_home': round(float(np.mean(rng.poisson(est['shots_home'], simulations))), 1),
        'shots_away': round(float(np.mean(rng.poisson(est['shots_away'], simulations))), 1),
        'target_home': round(float(np.mean(rng.poisson(est['target_home'], simulations))), 1),
        'target_away': round(float(np.mean(rng.poisson(est['target_away'], simulations))), 1),
        'corners_home': round(float(np.mean(rng.poisson(est['corners_home'], simulations))), 1),
        'corners_away': round(float(np.mean(rng.poisson(est['corners_away'], simulations))), 1),
        'yellow_home': round(float(np.mean(rng.poisson(est['yellow_home'], simulations))), 1),
        'yellow_away': round(float(np.mean(rng.poisson(est['yellow_away'], simulations))), 1),
    }

    return {'results': top10, 'stats': stats}

# ------------------ SILNIK PREDYKCJI TABELI SEZONU ------------------

def simulate_league_table(season_code=CURRENT_SEASON, n_sims=SEASON_SIMULATIONS):
    season_matches = Match.query.filter_by(season=season_code).all()
    if not season_matches:
        latest = Match.query.order_by(Match.match_date.desc()).limit(380).all()
        if not latest:
            return None
        max_date = latest[0].match_date
        cutoff = datetime(max_date.year if max_date.month >= 7 else max_date.year - 1, 7, 1)
        season_matches = [m for m in latest if m.match_date and m.match_date >= cutoff]

    team_display = {}
    played_pairs = set()
    cur_pts = {}
    cur_gf = {}
    cur_ga = {}
    cur_mp = {}

    for m in season_matches:
        h, a = m.home_norm, m.away_norm
        team_display[h] = m.home_team
        team_display[a] = m.away_team
        played_pairs.add((h, a))

        for t in (h, a):
            cur_pts.setdefault(t, 0)
            cur_gf.setdefault(t, 0)
            cur_ga.setdefault(t, 0)
            cur_mp.setdefault(t, 0)

        cur_mp[h] += 1
        cur_mp[a] += 1
        cur_gf[h] += m.ft_home
        cur_ga[h] += m.ft_away
        cur_gf[a] += m.ft_away
        cur_ga[a] += m.ft_home

        if m.ft_home > m.ft_away:
            cur_pts[h] += 3
        elif m.ft_home < m.ft_away:
            cur_pts[a] += 3
        else:
            cur_pts[h] += 1
            cur_pts[a] += 1

    teams = sorted(team_display.keys())
    n_teams = len(teams)
    if n_teams < 2:
        return None

    team_idx = {t: i for i, t in enumerate(teams)}

    remaining_fixtures = []
    for h in teams:
        for a in teams:
            if h != a and (h, a) not in played_pairs:
                remaining_fixtures.append((h, a))

    pts_sim = np.tile([cur_pts[t] for t in teams], (n_sims, 1)).astype(np.int32)
    gd_sim = np.tile([cur_gf[t] - cur_ga[t] for t in teams], (n_sims, 1)).astype(np.int32)
    gf_sim = np.tile([cur_gf[t] for t in teams], (n_sims, 1)).astype(np.int32)
    ga_sim = np.tile([cur_ga[t] for t in teams], (n_sims, 1)).astype(np.int32)

    rng = np.random.default_rng()

    for h, a in remaining_fixtures:
        est = estimate_team_stats(h, a)
        i_h, i_a = team_idx[h], team_idx[a]

        if est['nb_home']:
            r_h, p_h = est['nb_home']
            gh = rng.negative_binomial(n=max(1, int(round(r_h))), p=np.clip(p_h, 1e-6, 1 - 1e-6), size=n_sims)
        else:
            gh = rng.poisson(lam=est['lambda_home'], size=n_sims)

        if est['nb_away']:
            r_a, p_a = est['nb_away']
            ga = rng.negative_binomial(n=max(1, int(round(r_a))), p=np.clip(p_a, 1e-6, 1 - 1e-6), size=n_sims)
        else:
            ga = rng.poisson(lam=est['lambda_away'], size=n_sims)

        gh += ((rng.random(n_sims) < 0.04) & (rng.random(n_sims) < 0.75)).astype(int)
        ga += ((rng.random(n_sims) < 0.04) & (rng.random(n_sims) < 0.75)).astype(int)

        pts_sim[:, i_h] += np.where(gh > ga, 3, np.where(gh == ga, 1, 0))
        pts_sim[:, i_a] += np.where(ga > gh, 3, np.where(gh == ga, 1, 0))
        gd_sim[:, i_h] += (gh - ga)
        gd_sim[:, i_a] += (ga - gh)
        gf_sim[:, i_h] += gh
        ga_sim[:, i_h] += ga
        gf_sim[:, i_a] += ga
        ga_sim[:, i_a] += gh

    composite_score = pts_sim * 1_000_000 + gd_sim * 1_000 + gf_sim
    order = np.argsort(-composite_score, axis=1)
    ranks = np.argsort(order, axis=1) + 1

    table_rows = []
    for i, t in enumerate(teams):
        team_ranks = ranks[:, i]
        table_rows.append({
            'team': team_display[t],
            'team_norm': t,
            'cur_mp': cur_mp[t],
            'cur_pts': cur_pts[t],
            'cur_gd': cur_gf[t] - cur_ga[t],
            'proj_pts': round(float(np.mean(pts_sim[:, i])), 1),
            'proj_gf': round(float(np.mean(gf_sim[:, i])), 1),
            'proj_ga': round(float(np.mean(ga_sim[:, i])), 1),
            'proj_gd': round(float(np.mean(gd_sim[:, i])), 1),
            'avg_rank': round(float(np.mean(team_ranks)), 2),
            'prob_title': round(float(np.mean(team_ranks == 1) * 100.0), 1),
            'prob_ucl': round(float(np.mean(team_ranks <= 4) * 100.0), 1),
            'prob_uel': round(float(np.mean((team_ranks >= 5) & (team_ranks <= 6)) * 100.0), 1),
            'prob_relegation': round(float(np.mean(team_ranks >= (n_teams - 2)) * 100.0), 1),
        })

    table_rows.sort(key=lambda x: (x['proj_pts'], x['proj_gd']), reverse=True)
    for idx, r in enumerate(table_rows, start=1):
        r['pos'] = idx

    return {
        'season': season_code,
        'played_matches': len(season_matches),
        'remaining_matches': len(remaining_fixtures),
        'simulations': n_sims,
        'table': table_rows
    }

# ------------------ ENDPOINTY BACKENDU ------------------

@app.route('/')
def index():
    teams = sorted(get_canonical_teams().values())
    matches_count = Match.query.count()
    return render_template('index.html', teams=teams, matches_count=matches_count)

@app.route('/api/predict', methods=['POST'])
def api_predict():
    data = request.get_json() or {}
    home_q = data.get('home', '').strip()
    away_q = data.get('away', '').strip()

    team_map = get_canonical_teams()
    home_norm = find_team_candidate(home_q, team_map)
    away_norm = find_team_candidate(away_q, team_map)

    if not home_norm or not away_norm:
        return jsonify({'error': 'Nie znaleziono drużyny w bazie Supabase.'}), 400
    if home_norm == away_norm:
        return jsonify({'error': 'Wybierz dwie różne drużyny.'}), 400

    out = simulate_match_forecast(home_norm, away_norm)
    return jsonify({
        'home_team': team_map[home_norm],
        'away_team': team_map[away_norm],
        'results': out['results'],
        'stats': out['stats']
    })

@app.route('/api/table', methods=['GET'])
def api_table():
    res = simulate_league_table()
    if not res:
        return jsonify({'error': 'Brak meczów aktualnego sezonu w bazie. Kliknij przycisk synchronizacji z API.'}), 400
    return jsonify(res)

@app.route('/api/sync', methods=['POST'])
def api_sync():
    try:
        from sync_laliga import sync_from_web
        res = sync_from_web()
        return jsonify({
            'message': f"Zsynchronizowano z API! Dodano {res['added_matches']} meczów i {res['added_odds']} kursów.",
            'total_matches': Match.query.count()
        })
    except Exception as e:
        return jsonify({'error': f'Błąd pobierania danych z API: {str(e)}'}), 500

if __name__ == '__main__':
    print("Otwórz w przeglądarce: http://127.0.0.1:5000")
    app.run(debug=True, host='127.0.0.1', port=5000)