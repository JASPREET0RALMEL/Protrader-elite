from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import yfinance as yf
import os
import requests

app = Flask(__name__)
CORS(app)

DB_NAME = "simulator.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, email TEXT UNIQUE, password TEXT, balance REAL DEFAULT 100000.0)")
        conn.execute("CREATE TABLE IF NOT EXISTS portfolio (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ticker TEXT, shares INTEGER, avg_price REAL)")
        conn.commit()

if not os.path.exists(DB_NAME): init_db()

def get_symbol_from_name(query):
    try:
        url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers).json()
        return response['quotes'][0]['symbol'] if response.get('quotes') else query.upper()
    except: return query.upper()

@app.route('/api/stock/<query>', methods=['GET'])
def get_stock(query):
    try:
        symbol = get_symbol_from_name(query)
        stock = yf.Ticker(symbol)
        hist = stock.history(period="1mo")
        if hist.empty: return jsonify({"success": False}), 404
        return jsonify({
            "success": True, "ticker": symbol, "name": stock.info.get('shortName', symbol),
            "price": round(hist['Close'].iloc[-1], 2),
            "history": {"dates": hist.index.strftime('%m-%d').tolist(), "prices": [round(p, 2) for p in hist['Close'].tolist()]}
        })
    except: return jsonify({"success": False}), 500

@app.route('/api/trade', methods=['POST'])
def trade():
    data = request.json
    uid, ticker, shares, price, side = data['user_id'], data['ticker'], int(data['shares']), float(data['price']), data['side']
    total = shares * price
    with get_db() as conn:
        user = conn.execute("SELECT balance FROM users WHERE id = ?", (uid,)).fetchone()
        if side == 'buy':
            if user['balance'] < total: return jsonify({"success": False, "message": "Low Balance"}), 400
            conn.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (total, uid))
            pos = conn.execute("SELECT * FROM portfolio WHERE user_id = ? AND ticker = ?", (uid, ticker)).fetchone()
            if pos:
                new_shares = pos['shares'] + shares
                new_avg = ((pos['shares'] * pos['avg_price']) + total) / new_shares
                conn.execute("UPDATE portfolio SET shares = ?, avg_price = ? WHERE id = ?", (new_shares, new_avg, pos['id']))
            else:
                conn.execute("INSERT INTO portfolio (user_id, ticker, shares, avg_price) VALUES (?, ?, ?, ?)", (uid, ticker, shares, price))
        else: # Sell Side
            pos = conn.execute("SELECT * FROM portfolio WHERE user_id = ? AND ticker = ?", (uid, ticker)).fetchone()
            if not pos or pos['shares'] < shares: return jsonify({"success": False, "message": "Insufficient shares"}), 400
            conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (total, uid))
            if pos['shares'] == shares: conn.execute("DELETE FROM portfolio WHERE id = ?", (pos['id'],))
            else: conn.execute("UPDATE portfolio SET shares = shares - ? WHERE id = ?", (shares, pos['id']))
        conn.commit()
        return jsonify({"success": True})

@app.route('/api/portfolio/<int:user_id>', methods=['GET'])
def get_portfolio(user_id):
    with get_db() as conn:
        user = conn.execute("SELECT balance FROM users WHERE id = ?", (user_id,)).fetchone()
        rows = conn.execute("SELECT * FROM portfolio WHERE user_id = ?", (user_id,)).fetchall()
        holdings = []
        total_equity = user['balance']
        for r in rows:
            h = dict(r)
            curr = yf.Ticker(h['ticker']).history(period="1d")['Close'].iloc[-1]
            h['current_price'] = round(curr, 2)
            h['pl'] = round((curr - h['avg_price']) * h['shares'], 2)
            total_equity += (curr * h['shares'])
            holdings.append(h)
        return jsonify({"balance": round(user['balance'], 2), "total_equity": round(total_equity, 2), "holdings": holdings})

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    try:
        with get_db() as conn:
            conn.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)", (data['username'], data['email'], data['password']))
            conn.commit()
            return jsonify({"success": True})
    except: return jsonify({"success": False, "message": "Email exists"}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email = ? AND password = ?", (data['email'], data['password'])).fetchone()
        if user: return jsonify({"success": True, "user_id": user['id'], "username": user['username'], "balance": user['balance']})
    return jsonify({"success": False}), 401

@app.route('/api/chat', methods=['POST'])
def chat():
    msg = request.json.get('message', '').lower()
    replies = {
        "buy": "Go to Trade, search for a company, and click 'Buy'!",
        "sell": "If you own shares, go to Trade and use the 'Sell' button.",
        "portfolio": "Check your 'Portfolio' tab to see profits and current holdings.",
        "hi": "Hello Aadi! Ready to analyze the market?",
        "hello": "Hi there! I'm your ProTrader AI."
    }
    for k, v in replies.items():
        if k in msg: return jsonify({"reply": v})
    return jsonify({"reply": "I can help you with trading, checking balance or portfolio!"})

if __name__ == '__main__': app.run(debug=True, port=5000)