import pandas as pd
import numpy as np
from datetime import datetime
from GBaseConnector import connect
import requests
import json
import sys
import time

# ==========1、配置区（根据实际情况修改）==========
GBASE_CFG = {
    "host": "110.42.238.172",
    "port": 5258,
    "user": "root",
    "password": "Chen641219!",
    "db": "fin_risk",
    "charset": "utf8"
}

TUGRAPH_CFG = {
    "host": "110.42.238.172",
    "rest_port": 7070,        # TuGraph HTTP REST API 端口
    "user": "admin",
    "password": "73@TuGraph",
    "graph_name": "fin_risk_graph",
    "timeout": 300
}

BATCH_SIZE = 200

# ==========2、GBase 连接与数据读取==========
def get_gbase_conn():
    """获取 GBase 数据库连接"""
    return connect(**GBASE_CFG)

def read_table(table_name: str, columns: list[str]) -> pd.DataFrame:
    """通用读取 GBase 表"""
    conn = get_gbase_conn()
    cols_str = ", ".join(columns)
    sql = f"SELECT {cols_str} FROM {table_name}"
    df = pd.read_sql(sql, conn)
    conn.close()
    print(f"  ✓ 读取 {table_name}: {len(df)} 条")
    return df

def read_all_data():
    """读取 GBase 全部四张表"""
    print("\n📥 步骤1: 从 GBase 读取数据...")
    customers = read_table("cust_info", [
        "cust_id", "cust_type", "cust_name", "id_card", "phone",
        "address", "credit_score", "register_date", "create_time"
    ])
    loans = read_table("loan_info", [
        "loan_id", "cust_id", "loan_amt", "loan_term", "rate",
        "loan_type", "start_date", "due_date", "overdue_days",
        "loan_status", "create_time"
    ])
    guarantees = read_table("guarantee_info", [
        "guar_id", "loan_id", "guar_cust_id", "borrow_cust_id",
        "guar_amt", "guar_type", "valid_start", "valid_end", "create_time"
    ])
    transactions = read_table("trans_info", [
        "trans_id", "out_cust_id", "in_cust_id", "trans_amt",
        "trans_type", "trans_time", "remark", "create_time"
    ])
    return customers, loans, guarantees, transactions

# ==========3、数据清洗==========
def _safe_int(series: pd.Series, default: int = 0) -> pd.Series:
    return pd.to_numeric(series, errors='coerce').fillna(default).astype(np.int64)

def _safe_float(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors='coerce').fillna(default).astype(np.float64)

def _safe_str(series: pd.Series) -> pd.Series:
    return series.fillna('').astype(str).str.strip()

def _safe_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors='coerce')

def clean_customers(df: pd.DataFrame) -> pd.DataFrame:
    """清洗客户表"""
    df = df.copy()
    df['cust_id'] = _safe_int(df['cust_id'])
    df['cust_type'] = pd.to_numeric(df['cust_type'], errors='coerce').fillna(1).astype(np.int8)
    df['credit_score'] = pd.to_numeric(df['credit_score'], errors='coerce').fillna(600).astype(np.int32)
    df['cust_name'] = _safe_str(df['cust_name'])
    df['id_card'] = _safe_str(df['id_card'])
    df['phone'] = _safe_str(df['phone'])
    df['address'] = _safe_str(df['address'])
    df['register_date'] = _safe_datetime(df['register_date'])
    df['create_time'] = _safe_datetime(df['create_time'])

    df = df.dropna(subset=['cust_id'])
    df = df[df['cust_id'] > 0]
    df = df.drop_duplicates(subset=['cust_id'], keep='last')
    df = df.reset_index(drop=True)

    print(f"  ✓ 客户清洗: {len(df)} 条有效")
    return df

def clean_loans(df: pd.DataFrame) -> pd.DataFrame:
    """清洗贷款表"""
    df = df.copy()
    df['loan_id'] = _safe_int(df['loan_id'])
    df['cust_id'] = _safe_int(df['cust_id'])
    df['loan_amt'] = _safe_float(df['loan_amt'])
    df['loan_term'] = pd.to_numeric(df['loan_term'], errors='coerce').fillna(12).astype(np.int16)
    df['rate'] = _safe_float(df['rate'], 0.06)
    df['loan_type'] = pd.to_numeric(df['loan_type'], errors='coerce').fillna(1).astype(np.int8)
    df['overdue_days'] = pd.to_numeric(df['overdue_days'], errors='coerce').fillna(0).astype(np.int32)
    df['loan_status'] = pd.to_numeric(df['loan_status'], errors='coerce').fillna(0).astype(np.int8)
    df['start_date'] = _safe_datetime(df['start_date'])
    df['due_date'] = _safe_datetime(df['due_date'])
    df['create_time'] = _safe_datetime(df['create_time'])

    df = df.dropna(subset=['loan_id', 'cust_id'])
    df = df[df['loan_id'] > 0]
    df = df[df['cust_id'] > 0]
    df = df[df['loan_amt'] >= 0]
    df = df.drop_duplicates(subset=['loan_id'], keep='last')
    df = df.reset_index(drop=True)

    print(f"  ✓ 贷款清洗: {len(df)} 条有效")
    return df

def clean_guarantees(df: pd.DataFrame) -> pd.DataFrame:
    """清洗担保表"""
    df = df.copy()
    df['guar_id'] = _safe_int(df['guar_id'])
    df['loan_id'] = _safe_int(df['loan_id'])
    df['guar_cust_id'] = _safe_int(df['guar_cust_id'])
    df['borrow_cust_id'] = _safe_int(df['borrow_cust_id'])
    df['guar_amt'] = _safe_float(df['guar_amt'])
    df['guar_type'] = pd.to_numeric(df['guar_type'], errors='coerce').fillna(1).astype(np.int8)
    df['valid_start'] = _safe_datetime(df['valid_start'])
    df['valid_end'] = _safe_datetime(df['valid_end'])
    df['create_time'] = _safe_datetime(df['create_time'])

    df = df.dropna(subset=['guar_id', 'guar_cust_id', 'borrow_cust_id'])
    df = df[df['guar_id'] > 0]
    df = df[df['guar_cust_id'] > 0]
    df = df[df['borrow_cust_id'] > 0]
    df = df[df['guar_cust_id'] != df['borrow_cust_id']]
    df = df[df['guar_amt'] >= 0]
    df = df.drop_duplicates(subset=['guar_id'], keep='last')
    df = df.reset_index(drop=True)

    print(f"  ✓ 担保清洗: {len(df)} 条有效")
    return df

def clean_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """清洗交易表"""
    df = df.copy()
    df['trans_id'] = _safe_int(df['trans_id'])
    df['out_cust_id'] = _safe_int(df['out_cust_id'])
    df['in_cust_id'] = _safe_int(df['in_cust_id'])
    df['trans_amt'] = _safe_float(df['trans_amt'])
    df['trans_type'] = pd.to_numeric(df['trans_type'], errors='coerce').fillna(3).astype(np.int8)
    df['remark'] = _safe_str(df['remark'])
    df['trans_time'] = _safe_datetime(df['trans_time'])
    df['create_time'] = _safe_datetime(df['create_time'])

    df = df.dropna(subset=['trans_id', 'out_cust_id', 'in_cust_id'])
    df = df[df['trans_id'] > 0]
    df = df[df['out_cust_id'] > 0]
    df = df[df['in_cust_id'] > 0]
    df = df[df['out_cust_id'] != df['in_cust_id']]
    df = df[df['trans_amt'] >= 0]
    df = df.drop_duplicates(subset=['trans_id'], keep='last')
    df = df.reset_index(drop=True)

    print(f"  ✓ 交易清洗: {len(df)} 条有效")
    return df

# ==========4、TuGraph REST API 客户端==========
class TuGraphClient:
    """TuGraph REST API 客户端，支持 JWT 认证"""

    def __init__(self, host: str, port: int, user: str, password: str,
                 graph_name: str, timeout: int = 300):
        self.base_url = f"http://{host}:{port}"
        self.user = user
        self.password = password
        self.graph_name = graph_name
        self.timeout = timeout
        self.jwt_token: str | None = None
        self.session = requests.Session()

    def login(self) -> bool:
        """登录获取 JWT token"""
        try:
            resp = self.session.post(
                f"{self.base_url}/login",
                json={"user": self.user, "password": self.password},
                timeout=self.timeout
            )
            if resp.status_code == 200:
                data = resp.json()
                if 'jwt' in data:
                    self.jwt_token = data['jwt']
                    self.session.headers.update({
                        "Authorization": f"Bearer {self.jwt_token}"
                    })
                    print("  ✓ TuGraph JWT 登录成功")
                    return True
                elif data.get('errorCode') == 0:
                    self.jwt_token = data.get('jwt', '')
                    if self.jwt_token:
                        self.session.headers.update({
                            "Authorization": f"Bearer {self.jwt_token}"
                        })
                        print("  ✓ TuGraph JWT 登录成功")
                        return True
            print(f"  ⚠️ JWT 登录响应: {resp.status_code} {resp.text[:200]}")
        except Exception as e:
            print(f"  ⚠️ JWT 登录异常: {e}")

        print("  ℹ️ 尝试使用 Basic Auth 方式...")
        self.session.auth = (self.user, self.password)
        return True

    def call_cypher(self, cypher: str, graph: str | None = None) -> tuple[bool, dict | str]:
        """执行 Cypher 查询"""
        if graph is None:
            graph = self.graph_name

        # TuGraph REST API: 正确字段名是 'graph' + 'script'，不是 'cypher'
        payload = {"graph": graph, "script": cypher}

        try:
            resp = self.session.post(
                f"{self.base_url}/cypher",
                json=payload,
                timeout=self.timeout
            )
            if resp.status_code == 200:
                result = resp.json()
                error_code = result.get('errorCode') or result.get('code')
                if error_code is None or error_code == 0:
                    return True, result
                return False, result
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
        except requests.exceptions.Timeout:
            return False, "请求超时"
        except Exception as e:
            return False, str(e)

    def call_plugin(self, plugin_type: str, plugin_name: str,
                    plugin_input: str, timeout: float = 0) -> tuple[bool, str]:
        """调用存储过程"""
        payload = {
            "plugin_type": plugin_type,
            "plugin_name": plugin_name,
            "plugin_input": plugin_input,
            "timeout": timeout
        }
        try:
            resp = self.session.post(
                f"{self.base_url}/load_plugin",
                json=payload,
                timeout=self.timeout
            )
            if resp.status_code == 200:
                return True, resp.text
            return False, resp.text
        except Exception as e:
            return False, str(e)

    def close(self):
        self.session.close()

# ==========5、TuGraph Schema 创建==========
def create_tugraph_schema(client: TuGraphClient):
    """创建 TuGraph 图模型 Schema

    TuGraph 4.5 是强 Schema 图数据库，
    必须通过 CALL 存储过程预先创建标签，不支持自动创建。
    """
    print("\n🏗️  步骤3: 创建 TuGraph Schema...")

    graph = client.graph_name

    vert_label = "Customer"
    vert_loan = "Loan"
    edge_guar = "Guarantees"
    edge_trans = "Transfers"
    edge_borrow = "BORROW"

    # ---------------------- 顶点标签创建 ----------------------
    create_label_cql = (
        f"CALL db.createVertexLabel('{vert_label}', "
        f"'cust_id', "
        f"'cust_id', 'INT64', false, "
        f"'cust_type', 'INT8', false, "
        f"'cust_name', 'STRING', false, "
        f"'id_card', 'STRING', false, "
        f"'phone', 'STRING', false, "
        f"'address', 'STRING', false, "
        f"'credit_score', 'INT32', false, "
        f"'register_date', 'STRING', false, "
        f"'create_time', 'STRING', false)"
    )

    create_loan_label_cql = (
        f"CALL db.createVertexLabel('{vert_loan}', "
        f"'loan_id', "
        f"'loan_id', 'INT64', false, "
        f"'cust_id', 'INT64', false, "
        f"'loan_amt', 'DOUBLE', false, "
        f"'loan_term', 'INT16', false, "
        f"'rate', 'DOUBLE', false, "
        f"'loan_type', 'INT8', false, "
        f"'start_date', 'STRING', false, "
        f"'due_date', 'STRING', false, "
        f"'overdue_days', 'INT32', false, "
        f"'loan_status', 'INT8', false, "
        f"'create_time', 'STRING', false)"
    )

    # ---------------------- 边标签创建（✅ 官方正确格式："[]"） ----------------------
    create_guar_edge_cql = (
        f"CALL db.createEdgeLabel('{edge_guar}', '[]', "
        f"'guar_id', 'INT64', false, "
        f"'loan_id', 'INT64', false, "
        f"'guar_amt', 'DOUBLE', false, "
        f"'guar_type', 'INT8', false, "
        f"'valid_start', 'STRING', false, "
        f"'valid_end', 'STRING', false, "
        f"'create_time', 'STRING', false)"
    )

    create_trans_edge_cql = (
        f"CALL db.createEdgeLabel('{edge_trans}', '[]', "
        f"'trans_id', 'INT64', false, "
        f"'trans_amt', 'DOUBLE', false, "
        f"'trans_type', 'INT8', false, "
        f"'trans_time', 'STRING', false, "
        f"'remark', 'STRING', false, "
        f"'create_time', 'STRING', false)"
    )

    create_borrow_edge_cql = (
        f"CALL db.createEdgeLabel('{edge_borrow}', '[]', "
        f"'loan_id', 'INT64', false, "
        f"'loan_amt', 'DOUBLE', false, "
        f"'loan_term', 'INT16', false, "
        f"'rate', 'DOUBLE', false, "
        f"'loan_type', 'INT8', false, "
        f"'start_date', 'STRING', false, "
        f"'due_date', 'STRING', false, "
        f"'overdue_days', 'INT32', false, "
        f"'loan_status', 'INT8', false, "
        f"'create_time', 'STRING', false)"
    )

    # ---------------------- 索引 ----------------------
    create_index_cqls = [
        f"CALL db.addIndex('{vert_label}', 'cust_name', false)",
        f"CALL db.addIndex('{vert_loan}', 'cust_id', false)",
        f"CALL db.addEdgeIndex('{edge_guar}', 'guar_id', true, false)",
        f"CALL db.addEdgeIndex('{edge_trans}', 'trans_id', true, false)",
    ]

    schema_steps = [
        ("创建 Customer 顶点标签", create_label_cql),
        ("创建 Loan 顶点标签", create_loan_label_cql),
        ("创建 Guarantees 边标签", create_guar_edge_cql),
        ("创建 Transfers 边标签", create_trans_edge_cql),
        ("创建 BORROW 边标签", create_borrow_edge_cql),
    ]

    all_ok = True
    for desc, cql in schema_steps:
        ok, res = client.call_cypher(cql, graph)
        if ok:
            print(f"  ✓ {desc}")
        else:
            err_msg = str(res).lower()
            if "exist" in err_msg or "already" in err_msg:
                print(f"  ⚠️ {desc} — 已存在，跳过")
            else:
                print(f"  ⚠️ {desc} 失败: {err_msg[:180]}")
                all_ok = False

    index_steps = [
        ("创建 Customer 名称索引", create_index_cqls[0]),
        ("创建 Loan cust_id 索引", create_index_cqls[1]),
        ("创建 Guarantees 唯一索引", create_index_cqls[2]),
        ("创建 Transfers 唯一索引", create_index_cqls[3]),
    ]
    for desc, cql in index_steps:
        ok, res = client.call_cypher(cql, graph)
        if ok:
            print(f"  ✓ {desc}")
        else:
            err_msg = str(res).lower()
            if "exist" in err_msg:
                print(f"  ⚠️ {desc} — 已存在，跳过")
            else:
                print(f"  ⚠️ {desc}: {err_msg[:150]}")

    print("  ✓ Schema 检查完成！可以正常写入数据啦！")
    return all_ok

# ==========6、数据导入 TuGraph==========
def _fmt_date(val):
    """格式化日期为字符串"""
    if pd.isna(val):
        return ""
    if isinstance(val, (pd.Timestamp, datetime)):
        return val.strftime("%Y-%m-%d %H:%M:%S")
    return str(val)

def _esc(s: str) -> str:
    """转义字符串中的单引号"""
    return s.replace("'", "''").replace("\\", "\\\\")


def import_customers(client: TuGraphClient, df: pd.DataFrame):
    """导入客户顶点（极简 CREATE 版）"""
    print(f"\n📤 导入客户顶点 (共 {len(df)} 条)...")
    total = len(df)
    success = 0
    fail = 0
    graph_name = client.graph_name

    for idx, row in df.iterrows():
        try:
            cql = (
                f"CREATE (n:Customer {{"
                f"cust_id:{int(row['cust_id'])}, "
                f"cust_type:{int(row['cust_type'])}, "
                f"cust_name:'{_esc(row['cust_name'])}', "
                f"id_card:'{_esc(row['id_card'])}', "
                f"phone:'{_esc(row['phone'])}', "
                f"address:'{_esc(row['address'])}', "
                f"credit_score:{int(row['credit_score'])}, "
                f"register_date:'{_fmt_date(row['register_date'])}', "
                f"create_time:'{_fmt_date(row['create_time'])}'"
                f"}})"
            )

            # 执行，失败只计数不抛错
            ok, _ = client.call_cypher(cql, graph_name)
            if ok:
                success += 1
            else:
                fail += 1
        except:
            fail += 1

        # 进度打印
        if (idx + 1) % 100 == 0 or (idx + 1) == total:
            print(f"  进度: {idx + 1}/{total}  成功:{success}  失败:{fail}")

    print(f"\n✅ 客户导入完成：成功 {success} 条，失败 {fail} 条")
    return success, fail




def import_loans(client: TuGraphClient, df: pd.DataFrame, valid_cust_ids: set):
    print(f"\n📤 导入贷款顶点及借贷边 (共 {len(df)} 条)...")
    total = len(df)
    success = 0
    fail = 0
    skipped = 0
    graph_name = client.graph_name

    for idx, row in df.iterrows():
        try:
            lid = int(row['loan_id'])
            cid = int(row['cust_id'])

            if cid not in valid_cust_ids:
                skipped += 1
                continue

            # ===================== 1. 创建 Loan（失败打日志，继续跑）=====================
            try:
                cql1 = (
                    f"CREATE (l:Loan {{"
                    f"loan_id:{lid}, cust_id:{cid}, "
                    f"loan_amt:{float(row['loan_amt'])}, "
                    f"loan_term:{int(row['loan_term'])}, "
                    f"rate:{float(row['rate'])}, "
                    f"loan_type:{int(row['loan_type'])}, "
                    f"start_date:'{_fmt_date(row['start_date'])}', "
                    f"due_date:'{_fmt_date(row['due_date'])}', "
                    f"overdue_days:{int(row['overdue_days'])}, "
                    f"loan_status:{int(row['loan_status'])}, "
                    f"create_time:'{_fmt_date(row['create_time'])}'"
                    f"}})"
                )
                ok1, res1 = client.call_cypher(cql1, graph_name)
                if not ok1:
                    print(f"[WARN] 创建Loan失败 loan_id={lid}，原因：{res1}")
            except Exception as e:
                print(f"[ERROR] 创建Loan异常 loan_id={lid}，{str(e)}")

            # ===================== 2. 创建 BORROW 边（带全属性！）=====================
            try:
                cql2 = (
                    f"MATCH (c:Customer {{cust_id:{cid}}}), (l:Loan {{loan_id:{lid}}}) "
                    f"CREATE (c)-[:BORROW {{"
                    f"loan_id:{lid}, "
                    f"loan_amt:{float(row['loan_amt'])}, "
                    f"loan_term:{int(row['loan_term'])}, "
                    f"rate:{float(row['rate'])}, "
                    f"loan_type:{int(row['loan_type'])}, "
                    f"start_date:'{_fmt_date(row['start_date'])}', "
                    f"due_date:'{_fmt_date(row['due_date'])}', "
                    f"overdue_days:{int(row['overdue_days'])}, "
                    f"loan_status:{int(row['loan_status'])}, "
                    f"create_time:'{_fmt_date(row['create_time'])}'"
                    f"}}]->(l)"
                )
                ok2, res2 = client.call_cypher(cql2, graph_name)
                if ok2:
                    success += 1
                else:
                    fail += 1
                    print(f"[WARN] 创建边失败 loan_id={lid}，原因：{res2}")
            except Exception as e:
                fail += 1
                print(f"[ERROR] 创建边异常 loan_id={lid}，{str(e)}")

        except Exception as e:
            fail += 1
            print(f"[FATAL] 未知异常 loan_id={lid}：{str(e)}")

        if (idx + 1) % 50 == 0:
            print(f"→ 进度：{idx+1}/{total} 成功:{success} 失败:{fail} 跳过:{skipped}")

    print(f"\n✅ 完成：成功 {success} 失败 {fail} 跳过 {skipped}")
    return success, fail, skipped

def import_guarantees(client: TuGraphClient, df: pd.DataFrame, valid_cust_ids: set):
    """导入担保边（极简逐条版）"""
    print(f"\n📤 导入担保边 (共 {len(df)} 条)...")
    total = len(df)
    success = 0
    fail = 0
    skipped = 0
    graph_name = client.graph_name

    for idx, row in df.iterrows():
        try:
            g_cid = int(row['guar_cust_id'])
            b_cid = int(row['borrow_cust_id'])

            if g_cid not in valid_cust_ids or b_cid not in valid_cust_ids:
                skipped += 1
                continue

            cql = (
                f"MATCH (a:Customer {{cust_id:{g_cid}}}), "
                f"(b:Customer {{cust_id:{b_cid}}}) "
                f"CREATE (a)-[:Guarantees {{"
                f"guar_id:{int(row['guar_id'])}, "
                f"loan_id:{int(row['loan_id'])}, "
                f"guar_amt:{float(row['guar_amt'])}, "
                f"guar_type:{int(row['guar_type'])}, "
                f"valid_start:'{_fmt_date(row['valid_start'])}', "
                f"valid_end:'{_fmt_date(row['valid_end'])}', "
                f"create_time:'{_fmt_date(row['create_time'])}'"
                f"}}]->(b)"
            )

            ok, _ = client.call_cypher(cql, graph_name)
            if ok:
                success += 1
            else:
                fail += 1
        except:
            fail += 1

        if (idx + 1) % 100 == 0 or (idx + 1) == total:
            print(f"  进度: {idx+1}/{total} 成功:{success} 失败:{fail} 跳过:{skipped}")

    print(f"\n✅ 担保边导入完成：成功 {success} 失败 {fail} 跳过 {skipped}")
    return success, fail, skipped

def import_transactions(client: TuGraphClient, df: pd.DataFrame, valid_cust_ids: set):
    """导入交易边（极简逐条版）"""
    print(f"\n📤 导入交易边 (共 {len(df)} 条)...")
    total = len(df)
    success = 0
    fail = 0
    skipped = 0
    graph_name = client.graph_name

    for idx, row in df.iterrows():
        try:
            out_cid = int(row['out_cust_id'])
            in_cid = int(row['in_cust_id'])

            if out_cid not in valid_cust_ids or in_cid not in valid_cust_ids:
                skipped += 1
                continue

            cql = (
                f"MATCH (a:Customer {{cust_id:{out_cid}}}), "
                f"(b:Customer {{cust_id:{in_cid}}}) "
                f"CREATE (a)-[:Transfers {{"
                f"trans_id:{int(row['trans_id'])}, "
                f"trans_amt:{float(row['trans_amt'])}, "
                f"trans_type:{int(row['trans_type'])}, "
                f"trans_time:'{_fmt_date(row['trans_time'])}', "
                f"remark:'{_esc(row['remark'])}', "
                f"create_time:'{_fmt_date(row['create_time'])}'"
                f"}}]->(b)"
            )

            ok, _ = client.call_cypher(cql, graph_name)
            if ok:
                success += 1
            else:
                fail += 1
        except:
            fail += 1

        if (idx + 1) % 100 == 0 or (idx + 1) == total:
            print(f"  进度: {idx+1}/{total} 成功:{success} 失败:{fail} 跳过:{skipped}")

    print(f"\n✅ 交易边导入完成：成功 {success} 失败 {fail} 跳过 {skipped}")
    return success, fail, skipped








def verify_import(client: TuGraphClient):
    """验证导入结果"""
    print("\n✅ 验证导入结果:")

    # 先测试 Cypher 连通性
    ok, res = client.call_cypher("MATCH (n) RETURN n LIMIT 1")
    if not ok:
        print(f"  ⚠️ Cypher 连通性测试失败: {str(res)[:200]}")
        print("  提示: 请检查 TuGraph REST API 端口是否正确 (默认 7070)")
        return

    queries = [
        (f"MATCH (n:Customer) RETURN count(n)", "客户顶点数"),
        (f"MATCH (n:Loan) RETURN count(n)", "贷款顶点数"),
        (f"MATCH ()-[e:BORROW]->() RETURN count(e)", "借贷边数"),
        (f"MATCH ()-[e:Guarantees]->() RETURN count(e)", "担保边数"),
        (f"MATCH ()-[e:Transfers]->() RETURN count(e)", "交易边数"),
    ]
    for cql, desc in queries:
        ok, res = client.call_cypher(cql)
        if ok and isinstance(res, dict):
            try:
                result_list = res.get('result', [])
                if result_list and len(result_list) > 0:
                    cnt = result_list[0][0] if isinstance(result_list[0], list) else result_list[0]
                    print(f"  {desc}: {cnt}")
                else:
                    print(f"  {desc}: 无法解析 -> {json.dumps(res, ensure_ascii=False)[:200]}")
            except Exception as e:
                print(f"  {desc}: 解析异常 -> {e}")
        else:
            print(f"  {desc}: 查询失败 -> {str(res)[:200]}")

# ==========7、主流程==========
def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║   GBase → TuGraph  金融风控数据迁移工具                       ║
║   读取 GBase → 数据清洗 → 写入 TuGraph 图数据库               ║
╚══════════════════════════════════════════════════════════════╝
""")

    # ---- 步骤1: 读取 GBase ----
    try:
        df_cust, df_loan, df_guar, df_trans = read_all_data()
    except Exception as e:
        print(f"❌ 从 GBase 读取数据失败: {e}")
        print("请检查: 1) GBase 服务是否运行  2) 表是否已创建  3) 网络是否可达")
        sys.exit(1)

    if df_cust.empty:
        print("❌ 客户表为空，请先生成测试数据")
        sys.exit(1)

    # ---- 步骤2: 数据清洗 ----
    print("\n🧹 步骤2: 数据清洗...")
    df_cust = clean_customers(df_cust)
    df_loan = clean_loans(df_loan)
    df_guar = clean_guarantees(df_guar)
    df_trans = clean_transactions(df_trans)

    valid_cust_ids = set(df_cust['cust_id'].astype(np.int64).tolist())
    print(f"  ✓ 有效客户 ID 数量: {len(valid_cust_ids)}")

    # ---- 步骤3: 连接 TuGraph 并创建 Schema ----
    print("\n🔗 连接 TuGraph...")
    client = TuGraphClient(
        host=TUGRAPH_CFG['host'],
        port=TUGRAPH_CFG['rest_port'],
        user=TUGRAPH_CFG['user'],
        password=TUGRAPH_CFG['password'],
        graph_name=TUGRAPH_CFG['graph_name'],
        timeout=TUGRAPH_CFG['timeout']
    )

    if not client.login():
        print("❌ 无法登录 TuGraph，请检查连接配置")
        print(f"   地址: {TUGRAPH_CFG['host']}:{TUGRAPH_CFG['rest_port']}")
        print(f"   用户: {TUGRAPH_CFG['user']}")
        sys.exit(1)

    create_tugraph_schema(client)

    # ---- 步骤4: 导入数据 ----
    print("\n📤 步骤4: 导入数据到 TuGraph...")
    t0 = time.time()

    cust_ok, cust_fail = import_customers(client, df_cust)

    loan_ok, loan_fail, loan_skip = import_loans(
        client, df_loan, valid_cust_ids
    )

    guar_ok, guar_fail, guar_skip = import_guarantees(
        client, df_guar, valid_cust_ids
    )

    trans_ok, trans_fail, trans_skip = import_transactions(
        client, df_trans, valid_cust_ids
    )

    elapsed = time.time() - t0
    print(f"\n⏱️  导入耗时: {elapsed:.1f} 秒")

    # ---- 步骤5: 验证 ----
    verify_import(client)
    client.close()

    # ---- 汇总 ----
    print("\n" + "=" * 60)
    print("🎉 数据迁移完成!")
    print(f"   客户顶点: 成功 {cust_ok}, 失败 {cust_fail}")
    print(f"   贷款顶点+BORROW: 成功 {loan_ok}, 失败 {loan_fail}, 跳过 {loan_skip}")
    print(f"   担保边:   成功 {guar_ok}, 失败 {guar_fail}, 跳过 {guar_skip}")
    print(f"   交易边:   成功 {trans_ok}, 失败 {trans_fail}, 跳过 {trans_skip}")
    print("=" * 60)

if __name__ == "__main__":
    main()