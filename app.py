import streamlit as st
import requests
import pandas as pd
import xmltodict
from collections import defaultdict
import time
import re
import os

# 设置页面标题和图标
st.set_page_config(
    page_title="代谢物分类工具",
    page_icon="🧪",
    layout="wide"
)

# 添加标题和描述
st.title("🧪 代谢物分类工具")
st.markdown("""
该工具可以帮助您查询代谢物的分类信息，包括：
- **HMDB** 数据库中的超类、类和子类信息
- **KEGG** 数据库中的代谢物类型和通路信息
- 自动判断代谢物是初级代谢物还是次级代谢物
""")

# 添加侧边栏说明
with st.sidebar:
    st.header("使用说明")
    st.markdown("""
    1. 上传包含代谢物名称的Excel文件（第一列应为代谢物名称）
    2. 点击"开始查询"按钮
    3. 等待查询完成（每个代谢物约需2-3秒）
    4. 下载结果文件
    """)
    st.markdown("---")
    st.markdown("**注意**: 查询速度受网络状况和API限制影响")

# HMDB搜索函数（通过名称获取ID）
def search_hmdb_id(compound_name):
    try:
        url = f"https://hmdb.ca/unearth/q?query={compound_name}&searcher=metabolites"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data['metabolites']:
                return data['metabolites'][0]['hmdb_id']
    except:
        pass
    return None

# 新版HMDB查询
def query_hmdb(metabolites, progress_bar):
    results = {}
    base_url = "https://hmdb.ca/metabolites/"
    
    for i, metab in enumerate(metabolites):
        try:
            # 更新进度条
            progress_bar.progress((i + 0.3) / len(metabolites), text=f"正在查询 HMDB: {metab}")
            
            # 第一步：获取HMDB ID
            hmdb_id = search_hmdb_id(metab)
            if not hmdb_id:
                results[metab] = {'hmdb_status': 'ID not found'}
                continue
                
            # 第二步：用ID查询详细数据
            url = f"{base_url}{hmdb_id}.xml"
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            
            data = xmltodict.parse(response.content)
            info = data.get('metabolite', {})
            
            classification = info.get('classification', {})
            pathways = info.get('pathways', {}).get('pathway', [])
            pathways = [pathways] if isinstance(pathways, dict) else pathways
            
            results[metab] = {
                'hmdb_id': hmdb_id,
                'super_class': classification.get('super_class', 'Unknown'),
                'class': classification.get('class', 'Unknown'),
                'sub_class': classification.get('sub_class', 'Unknown'),
                'hmdb_pathways': [p.get('name', '') for p in pathways if isinstance(p, dict)],
                'hmdb_status': 'Found'
            }
        except Exception as e:
            results[metab] = {
                'hmdb_status': f'Error: {str(e)}'
            }
        time.sleep(1)
    
    return results

# 增强版KEGG名称转ID
def get_kegg_id(compound_name):
    try:
        # 尝试精确匹配
        search_url = f"http://rest.kegg.jp/find/compound/{compound_name}"
        response = requests.get(search_url, timeout=10)
        if response.status_code == 200 and response.text:
            for line in response.text.split('\n'):
                if line:
                    kegg_id, name = re.split(r'\s+', line, maxsplit=1)
                    return kegg_id.split(':')[1]
    except:
        pass
    return None

# 新版KEGG查询
def query_kegg(metabolites, progress_bar):
    results = {}
    base_url = "http://rest.kegg.jp/"
    
    for i, metab in enumerate(metabolites):
        try:
            # 更新进度条
            progress_bar.progress((i + 0.7) / len(metabolites), text=f"正在查询 KEGG: {metab}")
            
            # 获取KEGG ID
            kegg_id = get_kegg_id(metab)
            if not kegg_id:
                results[metab] = {'kegg_status': 'ID not found'}
                continue
                
            # 获取详细信息
            info_url = f"{base_url}get/cpd:{kegg_id}"
            info_data = requests.get(info_url, timeout=15).text
            
            # 获取通路信息
            path_url = f"{base_url}link/pathway/cpd:{kegg_id}"
            path_data = requests.get(path_url, timeout=15).text
            pathways = [line.split("\t")[1].replace("path:", "") 
                       for line in path_data.split("\n") if line]
            
            # 判断代谢物类型
            metab_type = "secondary" if "Secondary metabolites" in info_data else "primary"
            
            results[metab] = {
                'kegg_id': kegg_id,
                'type': metab_type,
                'kegg_pathways': pathways,
                'description': info_data.split("\n")[1] if len(info_data.split("\n")) > 1 else "",
                'kegg_status': 'Found'
            }
        except Exception as e:
            results[metab] = {
                'kegg_status': f'Error: {str(e)}'
            }
        time.sleep(0.5)
    
    return results

# 分类主函数
def classify_metabolites(metabolites, progress_bar):
    hmdb_data = query_hmdb(metabolites, progress_bar)
    kegg_data = query_kegg(metabolites, progress_bar)
    
    classified = defaultdict(dict)
    for metab in metabolites:
        # 合并数据
        classified[metab].update(hmdb_data.get(metab, {}))
        classified[metab].update(kegg_data.get(metab, {}))
        
        # 确定最终类型
        if 'type' in classified[metab]:
            classified[metab]['final_type'] = classified[metab]['type']
        else:
            super_class = classified[metab].get('super_class', '').lower()
            if any(x in super_class for x in ['lipid', 'organic acid', 'nucleoside']):
                classified[metab]['final_type'] = 'primary'
            elif any(x in super_class for x in ['flavonoid', 'alkaloid', 'terpene']):
                classified[metab]['final_type'] = 'secondary'
            else:
                classified[metab]['final_type'] = 'unknown'
    
    return pd.DataFrame.from_dict(classified, orient='index')

# 文件上传区域
uploaded_file = st.file_uploader("上传Excel文件（第一列应为代谢物名称）", type=["xlsx", "xls"])

if uploaded_file is not None:
    try:
        # 读取文件
        df = pd.read_excel(uploaded_file)
        metabolites = df.iloc[:, 0].tolist()
        
        st.success(f"成功读取 {len(metabolites)} 个代谢物名称")
        
        # 显示前5个代谢物名称
        st.write("前5个代谢物名称:", metabolites[:5])
        
        # 开始查询按钮
        if st.button("开始查询"):
            # 创建进度条
            progress_bar = st.progress(0, text="准备开始查询...")
            
            # 执行查询
            result_df = classify_metabolites(metabolites, progress_bar)
            
            # 完成进度条
            progress_bar.progress(1.0, text="查询完成!")
            time.sleep(0.5)
            progress_bar.empty()
            
            st.success("查询完成!")
            
            # 结果展示（自动处理缺失列）
            display_cols = []
            for col in ['final_type', 'super_class', 'hmdb_pathways', 'kegg_pathways', 'hmdb_id', 'kegg_id']:
                if col in result_df.columns:
                    display_cols.append(col)
            
            # 显示结果表格
            st.dataframe(result_df[display_cols], height=500)
            
            # 下载按钮
            output = pd.ExcelWriter("metabolite_classification_results.xlsx", engine='xlsxwriter')
            result_df.to_excel(output, index=True)
            output.close()
            
            with open("metabolite_classification_results.xlsx", "rb") as file:
                st.download_button(
                    label="下载结果文件",
                    data=file,
                    file_name="metabolite_classification_results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    except Exception as e:
        st.error(f"发生错误: {str(e)}")
else:
    st.info("请上传Excel文件以开始查询")

# 添加页脚
st.markdown("---")
st.markdown("""
**数据来源**:  
- [HMDB (Human Metabolome Database)](https://hmdb.ca/)  
- [KEGG (Kyoto Encyclopedia of Genes and Genomes)](https://www.genome.jp/kegg/)  
""")