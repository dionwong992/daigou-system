import streamlit as st
import pandas as pd
from github import Github
import io
import base64
from PIL import Image
from datetime import datetime
import pytz

st.set_page_config(page_title="XiuXiu 多店家代购管家", layout="wide")

# --- 基础配置 ---
token = st.secrets["GITHUB_TOKEN"]
repo_name = st.secrets["REPO_NAME"] 
g = Github(token)
repo = g.get_repo(repo_name)

def get_kl_time():
    kl_tz = pytz.timezone('Asia/Kuala_Lumpur')
    return datetime.now(kl_tz)

def compress_image(uploaded_file):
    img = Image.open(uploaded_file)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((300, 300))
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=70)
    return base64.b64encode(buffer.getvalue()).decode()

st.title("👗 XiuXiu 代购 - 多店家 & 颜色库存系统")

tab_add, tab_stock, tab_import = st.tabs(["➕ 快速录入", "📦 库存明细", "📊 对单补货"])

# --- Tab 1: 录入（支持多店家） ---
with tab_add:
    st.info("💡 提示：同款号(Code)会自动共享照片，不分店家和颜色。")
    with st.form("add_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        code = col1.text_input("产品款号 (如 A01)")
        color = col2.text_input("颜色 (如 红色)")
        vendor = col3.text_input("店家名称 (如 老王家 / 档口B)")
        
        col4, col5, col6 = st.columns(3)
        cost = col4.number_input("该店家本钱", min_value=0.0)
        price = col5.number_input("建议卖价 (RM)", min_value=0.0)
        qty_in = col6.number_input("进货数量", min_value=0)
        
        pic = st.file_uploader("📸 衣服照片 (同款号只需传一次)", type=['jpg','jpeg','png'])
        
        if st.form_submit_button("🚀 确认入库"):
            if code and color and vendor:
                file = repo.get_contents("data.csv")
                df = pd.read_csv(io.StringIO(file.decoded_content.decode()))
                
                # 图片逻辑：自动寻找该款号(Code)的照片
                img_data = "无照片"
                if pic:
                    img_data = compress_image(pic)
                else:
                    # 只要 Code 相同就共享照片
                    existing_pics = df[df['Code'] == code]['照片'].unique()
                    pics_only = [p for p in existing_pics if p != "无照片"]
                    if pics_only: img_data = pics_only[0]
                
                # 检查是否存在 (款号 + 颜色 + 店家 三者匹配)
                idx = df[(df['Code'] == code) & (df['颜色'] == color) & (df['店家'] == vendor)].index
                
                if not idx.empty:
                    df.loc[idx, '现货件数'] += qty_in
                    # 如果该店家记录之前没图，现在补了图，更新它
                    if img_data != "无照片": df.loc[idx, '照片'] = img_data
                    st.success(f"✅ {vendor} 的 {code}-{color} 库存已增加！")
                else:
                    new_data = {
                        'Code': code, '颜色': color, '店家': vendor,
                        '本钱': cost, '卖价': price, '现货件数': qty_in, '照片': img_data
                    }
                    df = pd.concat([df, pd.DataFrame([new_data])], ignore_index=True)
                    st.success(f"✅ {vendor} 的新货 {code}-{color} 录入成功！")
                
                repo.update_file(file.path, f"Update {code}", df.to_csv(index=False), file.sha)
                st.rerun()

# --- Tab 2: 库存查看 ---
with tab_stock:
    try:
        file = repo.get_contents("data.csv")
        df_stock = pd.read_csv(io.StringIO(file.decoded_content.decode()))
        if not df_stock.empty:
            c1, c2 = st.columns(2)
            search_code = c1.text_input("🔍 按款号搜索")
            search_vendor = c2.text_input("🔍 按店家搜索")
            
            f_df = df_stock.copy()
            if search_code: f_df = f_df[f_df['Code'].str.contains(search_code, na=False, case=False)]
            if search_vendor: f_df = f_df[f_df['店家'].str.contains(search_vendor, na=False, case=False)]
            
            for i, row in f_df.iterrows():
                with st.container():
                    col_pic, col_info, col_btn = st.columns([1, 3, 1])
                    if row['照片'] != "无照片":
                        col_pic.image(base64.b64decode(row['照片']), width=100)
                    
                    col_info.markdown(f"**款号: {row['Code']} | 颜色: {row['颜色']}**")
                    col_info.write(f"🏠 店家: {row['店家']} | 💰 本钱: {row['本钱']}")
                    col_info.write(f"📦 现货: **{row['现货件数']} 件**")
                    
                    if col_btn.button("删除", key=f"del_{i}"):
                        df_stock = df_stock.drop(i)
                        repo.update_file(file.path, "Delete", df_stock.to_csv(index=False), file.sha)
                        st.rerun()
                st.divider()
    except: st.info("等待录入数据...")

# --- Tab 3: Excel 对单补货 ---
with tab_import:
    st.subheader("📊 订单 Excel 对单 (带店家区分)")
    st.warning("⚠️ Excel 列名需为：Code, 颜色, 店家, 数量")
    order_file = st.file_uploader("上传订单 Excel", type=['xlsx', 'xls'])
    if order_file:
        try:
            df_orders = pd.read_excel(order_file)
            file = repo.get_contents("data.csv")
            df_inv = pd.read_csv(io.StringIO(file.decoded_content.decode()))
            
            # 汇总订单：按款号+颜色+店家
            summary = df_orders.groupby(['Code', '颜色', '店家'])['数量'].sum().reset_index()
            
            results = []
            for _, order in summary.iterrows():
                c, col, v, n = str(order['Code']), str(order['颜色']), str(order['店家']), int(order['数量'])
                # 精准查找库存
                stock = df_inv[(df_inv['Code'].astype(str)==c) & 
                               (df_inv['颜色'].astype(str)==col) & 
                               (df_inv['店家'].astype(str)==v)]
                
                have = int(stock['现货件数'].values[0]) if not stock.empty else 0
                diff = n - have
                if diff > 0:
                    results.append({"款号":c, "颜色":col, "店家":v, "缺货数量":f"🔥 {diff}"})
            
            if results:
                st.table(pd.DataFrame(results))
            else:
                st.success("✅ 选定店家的现货全部充足！")
        except:
            st.error("Excel 格式有误，请确保包含：Code, 颜色, 店家, 数量")
