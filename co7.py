import concurrent.futures
import ccxt
import numpy as np
import pandas as pd
from scipy.signal import find_peaks
import streamlit as st
import ta

st.set_page_config(
    page_title="구조적 기댓값(EV) & 복리 트레이딩 대시보드",
    layout="wide",
)

# 세션 상태 초기화
for key in ['long_tab1', 'short_tab1', 'analyzed_1']:
    if key not in st.session_state:
        st.session_state[key] = None if key == 'analyzed_1' else pd.DataFrame()

# BTC는 별도 그룹이므로 메이저 알트에서 제외
MAJOR_ALTS = {'ETH', 'SOL', 'XRP', 'BNB', 'ADA', 'AVAX', 'DOT', 'LINK', 'SUI', 'APT', 'BCH', 'NEAR', 'DOGE'}
FEE_SLIPPAGE = 0.0012

def get_coin_tier(base_sym):
    """코인을 3단계 그룹으로 분류: 0(BTC), 1(메이저 알트), 2(일반 알트)"""
    if base_sym == 'BTC': return 0
    elif base_sym in MAJOR_ALTS: return 1
    else: return 2

# ==========================================
# 1. 거시 유동성 & 합성 마켓 지표 (BTC.D, TOTAL 등)
# ==========================================
@st.cache_data(ttl=600)
def fetch_synthetic_macro_data(market_type='swap'):
    ex = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': market_type}})
    supplies = {'BTC': 19760000, 'ETH': 120300000, 'BNB': 145000000, 'SOL': 468000000, 'XRP': 56300000000}
    USDT_CAP = 120_000_000_000  
    
    suffix = '/USDT:USDT' if market_type == 'swap' else '/USDT'
    dfs = []
    
    for s in supplies.keys():
        sym = s + suffix
        try:
            data = ex.fetch_ohlcv(sym, timeframe='1d', limit=60)
            if data and len(data) >= 20:
                df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                dfs.append(df['close'].rename(s))
        except:
            continue
            
    if not dfs: return None
    macro_df = pd.concat(dfs, axis=1).dropna()
    
    base_cols = list(macro_df.columns)
    for col in base_cols:
        macro_df[col + '_cap'] = macro_df[col] * supplies[col]
        
    macro_df['Total_Cap'] = macro_df[[c + '_cap' for c in base_cols]].sum(axis=1) + USDT_CAP
    macro_df['BTC.D'] = (macro_df['BTC_cap'] / macro_df['Total_Cap']) * 100
    macro_df['USDT.D'] = (USDT_CAP / macro_df['Total_Cap']) * 100
    macro_df['TOTAL2'] = macro_df['Total_Cap'] - macro_df['BTC_cap']
    macro_df['TOTAL3'] = macro_df['TOTAL2'] - macro_df['ETH_cap']
    
    return macro_df

def evaluate_trend(series):
    sma20 = series.rolling(20).mean()
    curr = series.iloc[-1]
    return "상승 ↗️" if curr > sma20.iloc[-1] else "하락 ↘️", curr

def render_advanced_macro_weather_panel(market_type):
    st.markdown('### 🌤️ 거시적 방향성 및 유동성 분석 (Macro Regime)')
    
    with st.spinner('BTC.D, USDT.D, TOTAL 지표 분석 중...'):
        macro_df = fetch_synthetic_macro_data(market_type)
        
    if macro_df is None or macro_df.empty:
        st.error("거시 데이터를 불러올 수 없습니다.")
        return

    btc_t, btc_v = evaluate_trend(macro_df['BTC'])
    btcd_t, btcd_v = evaluate_trend(macro_df['BTC.D'])
    usdtd_t, usdtd_v = evaluate_trend(macro_df['USDT.D'])
    tot2_t, tot2_v = evaluate_trend(macro_df['TOTAL2'])
    tot3_t, tot3_v = evaluate_trend(macro_df['TOTAL3'])

    # 분석 총평 생성 로직
    if "하락" in usdtd_t and "상승" in btcd_t:
        btc_summary = "시장 자금이 비트코인으로 강하게 유입되며 상승을 주도하고 있습니다."
    elif "상승" in btc_t:
        btc_summary = "비트코인이 견조한 상승 추세를 유지하고 있습니다."
    else:
        btc_summary = "비트코인 상승 모멘텀이 둔화되거나 가격 조정을 겪고 있습니다."

    if "하락" in btcd_t and "상승" in tot3_t:
        alt_summary = "비트코인 도미넌스가 꺾이며 알트코인 전반으로 자금이 확산되고 있습니다."
    elif "상승" in tot2_t:
        alt_summary = "이더리움 등 대형 알트코인 위주로 자금이 방어되고 있습니다."
    else:
        alt_summary = "알트코인 시장 내 유동성이 부족하여 개별 호재 장세가 예상됩니다."

    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown('**👑 BTC 관점 (Bitcoin)**')
        st.write(f"- **BTC 가격:** `{btc_t}`")
        st.write(f"- **BTC 도미넌스:** `{btcd_t}` ({btcd_v:.1f}%)")
        st.info(f"**총평:** {btc_summary}")
        
    with col2:
        st.markdown('**💎 알트 관점 (Altcoins)**')
        st.write(f"- **USDT 도미넌스(현금화 비중):** `{usdtd_t}` ({usdtd_v:.1f}%)")
        st.write(f"- **TOTAL3 (일반 알트 시총):** `{tot3_t}`")
        st.info(f"**총평:** {alt_summary}")
        
    with col3:
        st.markdown('**🎯 종합 시장 진단 및 트레이딩 전략**')
        if "상승" in usdtd_t:
            st.error("**[리스크 관리 / 현금 관망 장세]**\n\n가상자산 시장에서 테더(현금) 비중이 늘며 자금이 이탈 중입니다. 무리한 매수(롱)를 자제하고, 숏 포지션이나 관망을 권장합니다.")
        elif "하락" in usdtd_t and "상승" in btcd_t:
            st.success("**[비트코인 주도 랠리 장세]**\n\n시장의 유동성이 비트코인으로 집중되고 있습니다. 알트코인보다는 **BTC 및 대형 메이저 코인의 롱(매수) 포지션**에 자금을 집중하는 것이 유리합니다.")
        elif "하락" in usdtd_t and "하락" in btcd_t and "상승" in tot3_t:
            st.warning("**[알트코인 순환매(불장) 장세]**\n\n비트코인의 자금이 알트코인으로 흘러가고 있습니다. **일반 알트코인 스캔 결과**에서 기댓값이 높은 종목들을 적극적으로 공략하세요.")
        else:
            st.info("**[방향성 탐색 장세]**\n\n거시적 방향성이 뚜렷하지 않습니다. 변동성이 확실한 코인 위주로 짧게 방망이를 잡고, 시스템이 추천하는 통계적 우위 타점에만 선별 진입하세요.")
            
    st.markdown('---')

# ==========================================
# 2. 비트겟 데이터 로더 & 동적 구조 분석 엔진 (3단계 분류)
# ==========================================
@st.cache_data(ttl=300)
def load_market_data(market_type='swap'):
    ex = ccxt.bitget({'enableRateLimit': True, 'options': {'defaultType': market_type}})
    try:
        markets, tickers = ex.load_markets(), ex.fetch_tickers()
        data = []
        for sym, m in markets.items():
            if not m.get('active', True): continue
            if market_type == 'swap' and not (m.get('swap') and m.get('quote') == 'USDT'): continue
            if market_type == 'spot' and not (m.get('spot') and m.get('quote') == 'USDT'): continue
            
            t = tickers.get(sym)
            if not t: continue
            
            base = m.get('base')
            q_vol = t.get('quoteVolume', 0) or 0
            tier = get_coin_tier(base)
            
            # BTC, 메이저는 거래량 무관 패스, 일반 알트는 거래량 필터
            if tier == 2 and q_vol < 1000000: continue
            
            data.append({'symbol': sym, 'base': base, 'tier': tier, 'current_price': t.get('last', 0) or 0})
        return pd.DataFrame(data), ex
    except Exception:
        return pd.DataFrame(), None

def prep_structural_data(df, tier):
    df_c = df.copy()
    df_c['ATR'] = ta.volatility.average_true_range(df_c['High'], df_c['Low'], df_c['Close'], 14)
    df_c['ADX'] = ta.trend.ADXIndicator(df_c['High'], df_c['Low'], df_c['Close'], 14).adx()
    
    closes, highs, lows = df_c['Close'].values, df_c['High'].values, df_c['Low'].values
    
    # 3단계 티어별 파라미터 적용
    if tier == 0:    # BTC: 매우 매끄러움
        window, std_mult, prom_mult, dist = 60, 1.5, 0.15, 3
    elif tier == 1:  # 메이저 알트
        window, std_mult, prom_mult, dist = 55, 1.8, 0.25, 4
    else:            # 일반 알트: 노이즈 심함
        window, std_mult, prom_mult, dist = 50, 2.0, 0.40, 5

    upper, lower, mid = np.full(len(closes), np.nan), np.full(len(closes), np.nan), np.full(len(closes), np.nan)
    for i in range(window, len(closes)):
        y = closes[i-window:i]
        x = np.arange(window)
        poly = np.polyfit(x, y, 1)
        line = poly[0] * x + poly[1]
        std = np.std(y - line)
        mid[i], upper[i], lower[i] = line[-1], line[-1] + (std_mult * std), line[-1] - (std_mult * std)
        
    df_c['Ch_Upper'], df_c['Ch_Mid'], df_c['Ch_Lower'] = upper, mid, lower

    p_res, p_sup = np.full(len(closes), np.nan), np.full(len(closes), np.nan)
    atr_mean = df_c['ATR'].mean()
    
    peak_idx, _ = find_peaks(highs, distance=dist, prominence=atr_mean * prom_mult)
    trough_idx, _ = find_peaks(-lows, distance=dist, prominence=atr_mean * prom_mult)
    
    last_r, last_s = highs[0], lows[0]
    for i in range(len(closes)):
        if i in peak_idx: last_r = highs[i]
        if i in trough_idx: last_s = lows[i]
        p_res[i], p_sup[i] = last_r, last_s
        
    df_c['Pivot_R'], df_c['Pivot_S'] = p_res, p_sup
    return df_c

# ==========================================
# 3. 기댓값(EV) 백테스트 & 가변 필터링 엔진
# ==========================================
def evaluate_structural_entry(df, i, is_short=False, min_rrr=1.3):
    entry = df['Close'].iloc[i]
    sup = max(df['Pivot_S'].iloc[i], df['Ch_Lower'].iloc[i])
    res = min(df['Pivot_R'].iloc[i], df['Ch_Upper'].iloc[i])
    
    if np.isnan(sup) or np.isnan(res): return None

    if not is_short:
        if entry > df['Ch_Mid'].iloc[i]: return None
        sl = sup * 0.996
        tp = res * 0.996
        risk, reward = entry - sl, tp - entry
    else:
        if entry < df['Ch_Mid'].iloc[i]: return None
        sl = res * 1.004
        tp = sup * 1.004
        risk, reward = sl - entry, entry - tp

    if risk <= 0 or reward <= 0: return None
    rrr = reward / risk
    
    if rrr < min_rrr: return None
    return {'entry': entry, 'tp': tp, 'sl': sl, 'rrr': rrr}

def run_ev_backtest(df, is_short, tier, is_test_split=False):
    trades = []
    adx = df['ADX'].fillna(0).values
    
    # 3단계 티어별 진입 허들 (메이저 코인이 추천되도록 문턱 완화)
    if tier == 0:
        adx_thresh, min_rrr, min_trades_req = 10.0, 1.2, 1
    elif tier == 1:
        adx_thresh, min_rrr, min_trades_req = 14.0, 1.3, 1
    else:
        adx_thresh, min_rrr, min_trades_req = 18.0, 1.5, 2
        
    if is_test_split: min_trades_req = 1
    
    for i in range(50, len(df)-1):
        if adx[i] < adx_thresh: continue
        setup = evaluate_structural_entry(df, i, is_short, min_rrr=min_rrr)
        if not setup: continue
        
        entry, tp, sl = setup['entry'], setup['tp'], setup['sl']
        exit_p = entry
        
        post_df = df.iloc[i+1 : min(i+1+20, len(df))]
        for k in range(len(post_df)):
            h, l, c = post_df['High'].iloc[k], post_df['Low'].iloc[k], post_df['Close'].iloc[k]
            if not is_short:
                if h >= tp: exit_p = tp; break
                elif l <= sl: exit_p = sl; break
                else: exit_p = c
            else:
                if l <= tp: exit_p = tp; break
                elif h >= sl: exit_p = sl; break
                else: exit_p = c
                
        ret = ((exit_p - entry) / entry) if not is_short else ((entry - exit_p) / entry)
        trades.append(ret - FEE_SLIPPAGE)

    if len(trades) < min_trades_req: return None
    
    t_arr = np.array(trades)
    win_trades, lose_trades = t_arr[t_arr > 0], t_arr[t_arr <= 0]
    
    win_rate = len(win_trades) / len(t_arr)
    avg_win = np.mean(win_trades) if len(win_trades) > 0 else 0
    avg_loss = abs(np.mean(lose_trades)) if len(lose_trades) > 0 else 1e-9
    avg_rrr = avg_win / avg_loss if avg_loss > 0 else 0
    
    ev = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
    raw_kelly = win_rate - ((1 - win_rate) / avg_rrr) if avg_rrr > 0 else 0
    
    return {'win_rate': round(win_rate * 100, 1), 'ev_score': ev * 100, 'raw_kelly': raw_kelly}

def analyze_symbol(ex, row, is_short, tf):
    sym, base, tier = row['symbol'], row['base'], row['tier']
    try:
        ohlcv = ex.fetch_ohlcv(sym, timeframe=tf, limit=1000)
        if not ohlcv or len(ohlcv) < 100: return None
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df = prep_structural_data(df, tier)
        
        split = int(len(df) * 0.7)
        train, test = df.iloc[:split], df.iloc[split:]
        
        res_train = run_ev_backtest(train, is_short, tier, is_test_split=False)
        if not res_train or res_train['ev_score'] <= 0 or res_train['raw_kelly'] <= 0: return None
        
        res_test = run_ev_backtest(test, is_short, tier, is_test_split=True)
        if not res_test or res_test['ev_score'] <= 0 or res_test['raw_kelly'] <= 0: return None
        
        # 티어별 최소 RRR 재적용
        min_rrr = 1.2 if tier == 0 else (1.3 if tier == 1 else 1.5)
        current_setup = evaluate_structural_entry(df, len(df)-1, is_short, min_rrr=min_rrr)
        if not current_setup: return None
        
        cp, tp, sl = df['Close'].iloc[-1], current_setup['tp'], current_setup['sl']
        
        return {
            'symbol': sym, 'base': base, 'tier': tier, 'current_price': cp,
            'win_rate': res_test['win_rate'], 'ev_score': round(res_test['ev_score'], 2),
            'raw_kelly': res_test['raw_kelly'], 'current_rrr': round(current_setup['rrr'], 2),
            'tp_price': tp, 'sl_price': sl,
            'tp_pct': round(abs((tp - cp) / cp) * 100, 2), 'sl_pct': round(abs((sl - cp) / cp) * 100, 2)
        }
    except Exception: return None

def run_pipeline(ex, df_all, is_short, tf):
    results = []
    rows = [row for _, row in df_all.iterrows()]
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(analyze_symbol, ex, row, is_short, tf): row for row in rows}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res: results.append(res)
    if not results: return pd.DataFrame()
    return pd.DataFrame(results).sort_values(by=['ev_score', 'raw_kelly'], ascending=[False, False])

# ==========================================
# 4. Streamlit UI 렌더링
# ==========================================
st.title("대시보드")
st.caption("거시 분석과 티어별(BTC/메이저/일반) 맞춤 분석을 통해 최적의 기댓값 타점을 도출합니다.")

with st.sidebar:
    st.header("⚙️ 분석 및 복리 설정")
    selected_market = st.radio("거래 마켓:", ["선물 (USDT-M)", "현물 (Spot)"], index=0)
    market_type = 'swap' if "선물" in selected_market else 'spot'
    selected_tf = st.selectbox("⏱️ 타임프레임:", ["15m", "1h", "4h", "1d"], index=1)
    
    st.markdown("---")
    st.markdown("### 💸 복리 자금 관리")
    account_equity = st.number_input("현재 계좌 총 자산 (USDT):", value=10000.0, step=1000.0)
    kelly_mode = st.radio("복리 운용 모드:", ["Half-Kelly (안정적)", "Full-Kelly (공격적)"])

render_advanced_macro_weather_panel(market_type)
df_all, exchange = load_market_data(market_type)

if not df_all.empty and exchange:
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button('🎯 티어별 최적화 스캔 실행', use_container_width=True, type='primary'):
            with st.spinner('⏳ 각 코인의 특성에 맞춘 알고리즘 분석 중...'):
                st.session_state['long_tab1'] = run_pipeline(exchange, df_all, False, selected_tf)
                st.session_state['short_tab1'] = run_pipeline(exchange, df_all, True, selected_tf)
                st.session_state['analyzed_1'] = True
            st.success('스캔 및 복리 자금 계산 완료!')
            
    with col_btn2:
        if st.button('🔄 새로고침', use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    st.markdown('---')

    def draw_recommendation_cards(df, is_long):
        if df.empty:
            st.info("현재 조건에 부합하는 타점이 없습니다. (변동성/추세 부족)")
            return
            
        icon = "🟢" if is_long else "🔴"
        kelly_multiplier = 0.5 if "Half" in kelly_mode else 1.0
        
        for _, item in df.iterrows():
            applied_kelly_pct = min(item['raw_kelly'] * kelly_multiplier, 0.30) 
            pos_size_usdt = account_equity * applied_kelly_pct
            
            label = (
                f"{icon} {item['symbol']} | "
                f"🎯 TP: ${item['tp_price']:,.4f} | "
                f"🛑 SL: ${item['sl_price']:,.4f} | "
                f"승률: {item['win_rate']}% | "
                f"🔥 진입금: ${pos_size_usdt:,.0f}"
            )
            
            with st.expander(label):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**현재가:** `${item['current_price']:,.4f}`")
                    st.markdown(f"**구조적 손익비:** `1 : {item['current_rrr']}`")
                    st.markdown(f"**과거 검증 승률:** `{item['win_rate']}%`")
                    if is_long:
                        st.markdown(f"**수익/손실 폭:** TP `+{item['tp_pct']}%` / SL `-{item['sl_pct']}%`")
                    else:
                        st.markdown(f"**수익/손실 폭:** TP `-{item['tp_pct']}%` / SL `+{item['sl_pct']}%`")
                        
                with col2:
                    st.markdown(f"**기댓값(EV Score):** `+{item['ev_score']}%`")
                    st.markdown(f"**투입 자산 비중:** `{applied_kelly_pct*100:.1f}%` (최대 30% 제한)")
                    st.markdown(f"**💸 추천 진입 투입금:** `<span style='color: #00ff00; font-size: 1.1em;'><b>${pos_size_usdt:,.2f}</b></span>`", unsafe_allow_html=True)

    def render_results(long_df, short_df):
        if not st.session_state.get('analyzed_1'):
            st.info('상단의 **스캔 실행 버튼**을 눌러 분석을 진행하세요.')
            return

        col_L, col_S = st.columns(2)
        
        with col_L:
            st.markdown('### 📈 롱 (Long) 추천')
            # 3단계 탭 구성
            t1_L, t2_L, t3_L = st.tabs(["👑 비트코인(BTC)", "💎 메이저 알트", "🌐 일반 알트"])
            with t1_L: draw_recommendation_cards(long_df[long_df['tier'] == 0] if not long_df.empty else pd.DataFrame(), True)
            with t2_L: draw_recommendation_cards(long_df[long_df['tier'] == 1] if not long_df.empty else pd.DataFrame(), True)
            with t3_L: draw_recommendation_cards(long_df[long_df['tier'] == 2] if not long_df.empty else pd.DataFrame(), True)

        with col_S:
            st.markdown('### 📉 숏 (Short) 추천')
            # 3단계 탭 구성
            t1_S, t2_S, t3_S = st.tabs(["👑 비트코인(BTC)", "💎 메이저 알트", "🌐 일반 알트"])
            with t1_S: draw_recommendation_cards(short_df[short_df['tier'] == 0] if not short_df.empty else pd.DataFrame(), False)
            with t2_S: draw_recommendation_cards(short_df[short_df['tier'] == 1] if not short_df.empty else pd.DataFrame(), False)
            with t3_S: draw_recommendation_cards(short_df[short_df['tier'] == 2] if not short_df.empty else pd.DataFrame(), False)

    render_results(st.session_state['long_tab1'], st.session_state['short_tab1'])