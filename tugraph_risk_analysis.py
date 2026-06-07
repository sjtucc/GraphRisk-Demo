# 导入JSON处理库，用于解析TuGraph返回的JSON数据
import json
# 导入sys系统库，用于程序退出和路径处理
import sys
# 导入time时间库，用于统计算法运行时间
import time
# 导入defaultdict默认字典，用于处理分组聚合数据
from collections import defaultdict
# 导入datetime日期时间库，用于记录检测时间
from datetime import datetime

# 导入NetworkX图分析框架，所有图算法依赖此库
import networkx as nx
# 导入requests网络请求库，用于调用TuGraph REST API
import requests
# 导入GBase连接器，用于连接GBase8a数据库
from GBaseConnector import connect

# ==================== 1、配置区（可根据业务需求修改） ====================

# GBase8a数据库连接配置，连接信息与to_gbase.py保持一致
GBASE_CFG = {
    "host": "110.42.238.172",      # GBase服务器IP地址
    "port": 5258,                   # GBase端口号，默认5258
    "user": "root",                 # GBase用户名
    "password": "Chen641219!",      # GBase密码
    "db": "fin_risk",               # 使用的数据库名
    "charset": "utf8"               # 字符集
}

# TuGraph图数据库连接配置，连接信息与gbase_to_tugraph.py保持一致
TUGRAPH_CFG = {
    "host": "110.42.238.172",       # TuGraph服务器IP地址
    "rest_port": 7070,              # TuGraph REST API端口，默认7070
    "user": "admin",                # TuGraph用户名
    "password": "73@TuGraph",       # TuGraph密码
    "graph_name": "fin_risk_graph", # TuGraph图名称
    "timeout": 300                  # 请求超时时间（秒）
}

# 批量插入每批次大小，GBase批量插入时每批处理200条记录
BATCH_SIZE = 200

# 多头借贷阈值：客户贷款笔数大于等于此值，标记为多头借贷风险
MULTI_HEAD_THRESHOLD = 3

# 担保环风险定级阈值：长度大于等于5个节点判定为高风险
CYCLE_LENGTH_HIGH = 5
# 长度大于等于3个节点小于5个节点判定为中风险，小于3为低风险
CYCLE_LENGTH_MEDIUM = 3

# 交易闭环风险定级阈值：长度大于等于6个节点判定为高风险
TRANS_CYCLE_LENGTH_HIGH = 6
# 长度大于等于4个节点小于6判定为中风险，小于4为低风险
TRANS_CYCLE_LENGTH_MEDIUM = 4

# 逾期传染距离阈值：客户到最近逾期节点的最短路径距离小于等于此值，判定为有传染风险
OVERDUE_CONTAGION_DISTANCE = 3


# ==================== 2、GBase 连接与工具函数 ====================

# 获取GBase数据库连接对象
def get_gbase_conn():
    # 使用配置参数创建并返回GBase连接
    return connect(**GBASE_CFG)


# 创建风控分析结果表，如果表不存在则自动创建
def ensure_result_tables():
    # 获取数据库连接
    conn = get_gbase_conn()
    # 创建游标对象用于执行SQL
    cur = conn.cursor()

    # 定义5张结果表的DDL语句
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS risk_guarantee_cycle (
            cycle_id BIGINT NOT NULL COMMENT '担保环唯一ID编号',
            cycle_length INT DEFAULT NULL COMMENT '担保环包含的节点数量',
            cycle_path VARCHAR(4096) DEFAULT NULL COMMENT '担保环路径字符串，形式：custA->custB->...->custA',
            cust_ids TEXT COMMENT '涉及的所有客户ID列表，逗号分隔',
            total_guar_amt DECIMAL(18,2) DEFAULT NULL COMMENT '担保环中所有担保金额总和',
            risk_level VARCHAR(16) DEFAULT NULL COMMENT '风险等级：HIGH高风险/MEDIUM中风险/LOW低风险',
            detect_time DATETIME DEFAULT NULL COMMENT '本次检测时间',
            PRIMARY KEY (cycle_id)
        ) ENGINE=EXPRESS DEFAULT CHARSET=utf8 TABLESPACE='sys_tablespace'
        COMMENT='担保环检测结果表，存储担保网络中检测到的环形结构'
        """,
        """
        CREATE TABLE IF NOT EXISTS risk_gang_detect (
            gang_id BIGINT NOT NULL COMMENT '团伙唯一编号',
            cust_id BIGINT NOT NULL COMMENT '团伙成员客户ID',
            cust_name VARCHAR(64) DEFAULT NULL COMMENT '客户名称',
            gang_size INT DEFAULT NULL COMMENT '该团伙总人数',
            gang_type VARCHAR(32) DEFAULT NULL COMMENT '团伙类型：担保团伙guarantee/交易团伙transaction',
            risk_score DECIMAL(8,4) DEFAULT NULL COMMENT '风险评分，0-1，分数越高风险越大',
            detect_time DATETIME DEFAULT NULL COMMENT '本次检测时间',
            PRIMARY KEY (gang_id, cust_id)
        ) ENGINE=EXPRESS DEFAULT CHARSET=utf8 TABLESPACE='sys_tablespace'
        COMMENT='团伙检测结果表，存储社区检测识别出的异常团伙'
        """,
        """
        CREATE TABLE IF NOT EXISTS risk_multi_head (
            cust_id BIGINT NOT NULL COMMENT '客户ID',
            cust_name VARCHAR(64) DEFAULT NULL COMMENT '客户名称',
            loan_count INT DEFAULT NULL COMMENT '该客户当前贷款笔数',
            total_loan_amt DECIMAL(18,2) DEFAULT NULL COMMENT '所有贷款总额',
            overdue_loan_count INT DEFAULT NULL COMMENT'其中逾期贷款笔数',
            max_overdue_days INT DEFAULT NULL COMMENT'最大逾期天数',
            risk_level VARCHAR(16) DEFAULT NULL COMMENT'风险等级HIGH/MEDIUM/LOW',
            detect_time DATETIME DEFAULT NULL COMMENT'检测时间',
            PRIMARY KEY (cust_id)
        ) ENGINE=EXPRESS DEFAULT CHARSET=utf8 TABLESPACE='sys_tablespace'
        COMMENT='多头借贷检测结果表，存储有多头借贷风险的客户'
        """,
        """
        CREATE TABLE IF NOT EXISTS risk_trans_cycle (
            cycle_id BIGINT NOT NULL COMMENT'交易闭环唯一ID',
            cycle_length INT DEFAULT NULL COMMENT'闭环包含节点数',
            cycle_path VARCHAR(4096) DEFAULT NULL COMMENT'闭环路径字符串',
            total_trans_amt DECIMAL(18,2) DEFAULT NULL COMMENT'闭环交易总额',
            risk_level VARCHAR(16) DEFAULT NULL COMMENT'风险等级HIGH/MEDIUM/LOW',
            detect_time DATETIME DEFAULT NULL COMMENT'检测时间',
            PRIMARY KEY (cycle_id)
        ) ENGINE=EXPRESS DEFAULT CHARSET=utf8 TABLESPACE='sys_tablespace'
        COMMENT='交易闭环检测结果表，存储资金循环走账的交易闭环'
        """,
        """
        CREATE TABLE IF NOT EXISTS risk_overdue_contagion (
            cust_id BIGINT NOT NULL COMMENT'客户ID',
            cust_name VARCHAR(64) DEFAULT NULL COMMENT'客户名称',
            overdue_neighbor_count INT DEFAULT NULL COMMENT'直接相邻的逾期客户数量',
            total_exposure_amt DECIMAL(18,2) DEFAULT NULL COMMENT'与逾期客户关联的总金额敞口',
            distance_to_overdue INT DEFAULT NULL COMMENT'到最近逾期客户的最短路径距离',
            risk_level VARCHAR(16) DEFAULT NULL COMMENT'风险等级HIGH/MEDIUM/LOW',
            detect_time DATETIME DEFAULT NULL COMMENT'检测时间',
            PRIMARY KEY (cust_id)
        ) ENGINE=EXPRESS DEFAULT CHARSET=utf8 TABLESPACE='sys_tablespace'
        COMMENT='逾期风险传染检测结果表，存储可能被逾期传染的客户'
        """
    ]

    # 遍历所有DDL语句依次执行
    for ddl in ddl_statements:
        try:
            # 执行CREATE TABLE语句
            cur.execute(ddl)
        except Exception as e:
            # 捕获异常，如果表已存在则会报错，但不影响后续执行，只打印警告
            print(f"  ⚠️ 建表警告: {str(e)[:120]}")

    # 提交事务，确保DDL操作生效
    conn.commit()
    # 关闭游标
    cur.close()
    # 关闭数据库连接
    conn.close()
    # 打印提示信息
    print("✓ 风险结果表就绪")


# 清空结果表，每次重新分析前清空旧结果
def truncate_result_table(table_name: str):
    # 获取数据库连接
    conn = get_gbase_conn()
    # 创建游标
    cur = conn.cursor()
    # 执行TRUNCATE TABLE清空表数据
    cur.execute(f"TRUNCATE TABLE {table_name}")
    # 提交事务
    conn.commit()
    # 关闭游标和连接
    cur.close()
    conn.close()


# 批量插入数据到GBase表，按BATCH_SIZE分批提交
def batch_insert(table_name: str, columns: list[str], rows: list[tuple]):
    # 如果没有数据，直接返回
    if not rows:
        return
    # 获取数据库连接
    conn = get_gbase_conn()
    # 创建游标
    cur = conn.cursor()
    # 根据列数生成对应数量的%s占位符
    placeholders = ",".join(["%s"] * len(columns))
    # 拼接列名字符串
    cols_str = ",".join(columns)
    # 构造INSERT SQL语句
    sql = f"INSERT INTO {table_name}({cols_str}) VALUES({placeholders})"

    # 按BATCH_SIZE分片，每批插入BATCH_SIZE条记录
    for i in range(0, len(rows), BATCH_SIZE):
        # 取出当前批次数据
        batch = rows[i:i + BATCH_SIZE]
        # 使用executemany批量执行插入
        cur.executemany(sql, batch)
        # 每批次提交一次事务，避免大事务
        conn.commit()

    # 插入完成后关闭游标和连接
    cur.close()
    conn.close()
    # 打印插入结果
    print(f"  ✓ {table_name} 写入 {len(rows)} 条")


# ==================== 3、TuGraph REST API 客户端类 ====================

# TuGraph REST API 客户端，负责与TuGraph通信，获取图数据
class TuGraphClient:
    # 构造函数，初始化连接参数
    def __init__(self, host: str, port: int, user: str, password: str,
                 graph_name: str, timeout: int = 300):
        # 拼接基础URL：http://host:port
        self.base_url = f"http://{host}:{port}"
        # 保存用户名
        self.user = user
        # 保存密码
        self.password = password
        # 保存图名称
        self.graph_name = graph_name
        # 保存请求超时时间
        self.timeout = timeout
        # JWT令牌初始化为None，登录后赋值
        self.jwt_token = None
        # 创建requests会话对象，保持连接
        self.session = requests.Session()

    # 登录方法，获取JWT令牌用于后续请求认证
    def login(self) -> bool:
        try:
            # 发送POST登录请求到/login端点
            resp = self.session.post(
                f"{self.base_url}/login",
                # 请求体JSON，包含用户名密码
                json={"user": self.user, "password": self.password},
                # 设置超时
                timeout=self.timeout
            )
            # 如果响应状态码为200表示请求成功
            if resp.status_code == 200:
                # 解析响应JSON
                data = resp.json()
                # 如果响应中包含jwt字段
                if 'jwt' in data:
                    # 保存JWT令牌到实例变量
                    self.jwt_token = data['jwt']
                    # 在session请求头中添加Authorization Bearer认证
                    self.session.headers.update({
                        "Authorization": f"Bearer {self.jwt_token}"
                    })
                    # 打印登录成功信息
                    print("  ✓ TuGraph JWT 登录成功")
                    # 返回登录成功
                    return True
                # 如果errorCode为0表示登录成功（不同版本格式可能不同）
                elif data.get('errorCode') == 0:
                    # 从响应中获取jwt令牌
                    self.jwt_token = data.get('jwt', '')
                    # 如果成功获取到jwt
                    if self.jwt_token:
                        # 添加认证头
                        self.session.headers.update({
                            "Authorization": f"Bearer {self.jwt_token}"
                        })
                        # 打印成功并返回True
                        print("  ✓ TuGraph JWT 登录成功")
                        return True
        except Exception as e:
            # 捕获异常，打印警告信息
            print(f"  ⚠️ JWT 登录异常: {e}")

        # JWT登录失败，尝试使用Basic Auth方式
        print("  ℹ️ 尝试使用 Basic Auth 方式...")
        # 使用requests session的auth属性设置Basic认证
        self.session.auth = (self.user, self.password)
        # 返回True表示继续尝试使用Basic Auth
        return True

    # 执行Cypher查询方法，传入Cypher语句返回结果
    def call_cypher(self, cypher: str, graph: str | None = None):
        # 如果没有指定图名称，使用默认图名称
        if graph is None:
            graph = self.graph_name
        # 构造请求体，TuGraph REST API要求字段为graph和script
        payload = {"graph": graph, "script": cypher}
        try:
            # 发送POST请求到/cypher端点
            resp = self.session.post(
                f"{self.base_url}/cypher",
                # JSON格式请求体
                json=payload,
                # 设置超时
                timeout=self.timeout
            )
            # 响应状态码为200表示成功
            if resp.status_code == 200:
                # 解析响应JSON
                result = resp.json()
                # 获取错误码，可能在errorCode或code字段中
                error_code = result.get('errorCode') or result.get('code')
                # 如果错误码为空或者为0表示执行成功
                if error_code is None or error_code == 0:
                    # 返回成功标志和结果
                    return True, result
                # 执行出错，返回失败标志和错误结果
                return False, result
            # 状态码不是200，返回失败
            return False, f"HTTP {resp.status_code}: {resp.text[:300]}"
        # 捕获超时异常
        except requests.exceptions.Timeout:
            # 返回超时错误
            return False, "请求超时"
        # 捕获其他异常
        except Exception as e:
            # 返回异常信息
            return False, str(e)

    # 关闭session，释放资源
    def close(self):
        # 关闭requests会话
        self.session.close()


# ==================== 4、从 TuGraph 读取各类数据 ====================

# 解析TuGraph Cypher查询返回的结果，提取表头和数据行
def _parse_cypher_result(result: dict):
    # 初始化结果行列表
    rows = []
    # 从结果中获取header字段
    header = result.get('header', [])
    # 从结果中获取result字段（实际数据）
    data = result.get('result', [])
    # 遍历每一行数据
    for row in data:
        # 如果行是字典类型
        if isinstance(row, dict):
            # 根据表头顺序取值
            rows.append([row.get(h, None) for h in header])
        # 如果行本身就是列表
        elif isinstance(row, list):
            # 直接添加到结果
            rows.append(row)
    # 返回表头和数据行
    return header, rows


# 从TuGraph读取所有客户顶点信息，返回{客户ID->名称}和{客户ID->征信评分}两个字典
def read_customers(client: TuGraphClient):
    # 打印日志
    print("\n📥 从 TuGraph 读取客户顶点...")
    # 构造Cypher查询：匹配所有Customer顶点，返回ID、名称、征信评分
    cypher = "MATCH (c:Customer) RETURN c.cust_id, c.cust_name, c.credit_score"
    # 调用Cypher执行
    ok, res = client.call_cypher(cypher)
    # 如果执行失败，打印错误并返回空字典
    if not ok:
        print(f"  ❌ 读取客户失败: {res}")
        return {}, {}
    # 解析查询结果得到表头和行数据
    header, rows = _parse_cypher_result(res)
    # 初始化客户名称字典
    cust_name = {}
    # 初始化征信评分字典
    cust_score = {}
    # 遍历每一行结果
    for row in rows:
        # 取出客户ID，转为int类型
        cid = int(row[0]) if row[0] is not None else 0
        # 取出客户名称，转为字符串
        name = str(row[1]) if row[1] else ""
        # 取出征信评分，转为int类型
        score = int(row[2]) if row[2] is not None else 600
        # 只保存ID大于0的有效客户
        if cid > 0:
            # 保存名称到字典
            cust_name[cid] = name
            # 保存征信评分到字典
            cust_score[cid] = score
    # 打印读取结果统计
    print(f"  ✓ 读取客户: {len(cust_name)} 个")
    # 返回两个字典
    return cust_name, cust_score


# 从TuGraph读取所有担保边数据，返回列表[(源客户ID,目标客户ID,担保ID,担保金额),...]
def read_guarantees(client: TuGraphClient):
    # 打印日志
    print("\n📥 从 TuGraph 读取担保边...")
    # 构造Cypher查询：匹配所有Customer之间的Guarantees担保边，返回源ID、目标ID、担保ID、担保金额
    cypher = (
        "MATCH (a:Customer)-[e:Guarantees]->(b:Customer) "
        "RETURN a.cust_id, b.cust_id, e.guar_id, e.guar_amt"
    )
    # 执行Cypher查询
    ok, res = client.call_cypher(cypher)
    # 查询失败打印错误返回空列表
    if not ok:
        print(f"  ❌ 读取担保边失败: {res}")
        return []
    # 解析结果
    header, rows = _parse_cypher_result(res)
    # 初始化边列表
    edges = []
    # 遍历每一行
    for row in rows:
        # 源客户ID转int
        src = int(row[0]) if row[0] is not None else 0
        # 目标客户ID转int
        dst = int(row[1]) if row[1] is not None else 0
        # 担保ID转int
        guar_id = int(row[2]) if row[2] is not None else 0
        # 担保金额转float
        amt = float(row[3]) if row[3] is not None else 0.0
        # 只保留源ID和目标ID都大于0且源不等于目标的有效边
        if src > 0 and dst > 0 and src != dst:
            # 添加到边列表
            edges.append((src, dst, guar_id, amt))
    # 打印统计信息
    print(f"  ✓ 读取担保边: {len(edges)} 条")
    # 返回边列表
    return edges


# 从TuGraph读取所有交易边，返回列表[(转出ID,转入ID,交易ID,交易金额),...]
def read_transactions(client: TuGraphClient):
    # 打印日志
    print("\n📥 从 TuGraph 读取交易边...")
    # 构造Cypher查询：匹配Customer之间的Transfers交易边，返回转出ID、转入ID、交易ID、交易金额
    cypher = (
        "MATCH (a:Customer)-[e:Transfers]->(b:Customer) "
        "RETURN a.cust_id, b.cust_id, e.trans_id, e.trans_amt"
    )
    # 执行查询
    ok, res = client.call_cypher(cypher)
    # 失败返回空列表
    if not ok:
        print(f"  ❌ 读取交易边失败: {res}")
        return []
    # 解析结果
    header, rows = _parse_cypher_result(res)
    # 初始化边列表
    edges = []
    # 遍历每一行
    for row in rows:
        # 转出ID转int
        src = int(row[0]) if row[0] is not None else 0
        # 转入ID转int
        dst = int(row[1]) if row[1] is not None else 0
        # 交易ID转int
        tid = int(row[2]) if row[2] is not None else 0
        # 交易金额转float
        amt = float(row[3]) if row[3] is not None else 0.0
        # 过滤无效数据
        if src > 0 and dst > 0 and src != dst:
            # 添加到列表
            edges.append((src, dst, tid, amt))
    # 打印统计
    print(f"  ✓ 读取交易边: {len(edges)} 条")
    # 返回边列表
    return edges


# 从TuGraph读取所有借贷关系（客户-贷款），返回列表[(客户ID,贷款ID,贷款金额,逾期天数,贷款状态),...]
def read_borrows(client: TuGraphClient):
    # 打印日志
    print("\n📥 从 TuGraph 读取借贷关系...")
    # 构造Cypher查询：匹配客户向贷款的BORROW边，返回客户ID、贷款ID、金额、逾期天数、状态
    cypher = (
        "MATCH (c:Customer)-[e:BORROW]->(l:Loan) "
        "RETURN c.cust_id, l.loan_id, l.loan_amt, l.overdue_days, l.loan_status"
    )
    # 执行查询
    ok, res = client.call_cypher(cypher)
    # 失败返回空列表
    if not ok:
        print(f"  ❌ 读取借贷关系失败: {res}")
        return []
    # 解析结果
    header, rows = _parse_cypher_result(res)
    # 初始化借贷列表
    borrows = []
    # 遍历每一行
    for row in rows:
        # 客户ID转int
        cid = int(row[0]) if row[0] is not None else 0
        # 贷款ID转int
        lid = int(row[1]) if row[1] is not None else 0
        # 贷款金额转float
        amt = float(row[2]) if row[2] is not None else 0.0
        # 逾期天数转int
        overdue = int(row[3]) if row[3] is not None else 0
        # 贷款状态转int
        status = int(row[4]) if row[4] is not None else 0
        # 只保存有效客户ID
        if cid > 0:
            # 添加到列表
            borrows.append((cid, lid, amt, overdue, status))
    # 打印统计
    print(f"  ✓ 读取借贷关系: {len(borrows)} 条")
    # 返回结果
    return borrows


# 从TuGraph读取所有有逾期贷款的客户，返回逾期客户ID集合
def read_overdue_customers(client: TuGraphClient):
    # 打印日志
    print("\n📥 从 TuGraph 读取逾期客户...")
    # 构造Cypher查询：匹配逾期贷款对应的客户，去重返回
    cypher = (
        "MATCH (c:Customer)-[e:BORROW]->(l:Loan) "
        "WHERE l.overdue_days > 0 "
        "RETURN DISTINCT c.cust_id"
    )
    # 执行查询
    ok, res = client.call_cypher(cypher)
    # 查询失败打印警告返回空集合
    if not ok:
        print(f"  ⚠️ 读取逾期客户失败: {res}")
        return set()
    # 解析结果
    header, rows = _parse_cypher_result(res)
    # 初始化集合
    overdue_set = set()
    # 遍历每一行
    for row in rows:
        # 客户ID转int
        cid = int(row[0]) if row[0] is not None else 0
        # 只保存有效ID
        if cid > 0:
            # 添加到集合
            overdue_set.add(cid)
    # 打印统计
    print(f"  ✓ 逾期客户: {len(overdue_set)} 个")
    # 返回逾期客户ID集合
    return overdue_set


# ==================== 5、NetworkX 图构建 ====================

# 根据担保边构建担保关系有向图
def build_guarantee_graph(edges):
    # 创建NetworkX有向图对象
    G = nx.DiGraph()
    # 遍历所有担保边
    for src, dst, guar_id, amt in edges:
        # 添加边，保存担保ID和担保金额作为边属性
        G.add_edge(src, dst, guar_id=guar_id, guar_amt=amt)
    # 返回构建好的图
    return G


# 根据交易边构建交易关系有向图
def build_transaction_graph(edges):
    # 创建NetworkX有向图对象
    G = nx.DiGraph()
    # 遍历所有交易边
    for src, dst, tid, amt in edges:
        # 添加边，保存交易ID和交易金额作为属性
        G.add_edge(src, dst, trans_id=tid, trans_amt=amt)
    # 返回构建好的图
    return G


# 合并担保和交易边构建复合有向图，用于逾期传染等全局分析
def build_combined_graph(guar_edges, trans_edges):
    # 创建空的有向图
    G = nx.DiGraph()
    # 先添加所有担保边
    for src, dst, guar_id, amt in guar_edges:
        # 添加边，记录边类型为guarantee，ID和金额
        G.add_edge(src, dst, edge_type='guarantee', edge_id=guar_id, amt=amt)
    # 再添加所有交易边
    for src, dst, tid, amt in trans_edges:
        # 如果这两个节点之间已经有边（可能是担保边）
        if G.has_edge(src, dst):
            # 累计总金额，边类型标记为mixed混合
            G[src][dst]['amt'] = G[src][dst].get('amt', 0) + amt
            G[src][dst]['edge_type'] = 'mixed'
        else:
            # 没有边则直接添加，类型为transaction
            G.add_edge(src, dst, edge_type='transaction', edge_id=tid, amt=amt)
    # 返回合并后的复合图
    return G


# ==================== 6、风控算法实现 ====================

# 算法1：担保环检测，在担保图中寻找强连通分量中的环，返回结果列表
def detect_guarantee_cycles(G: nx.DiGraph, cust_name: dict, detect_time: str):
    # 打印日志
    print("\n🔍 算法1: 担保环检测...")

    # 如果图中没有边，直接返回空列表
    if G.number_of_edges() == 0:
        print("  ⚠️ 无边数据，跳过担保环检测")
        return []

    # 使用NetworkX强连通分量算法，得到所有强连通分量
    sccs = list(nx.strongly_connected_components(G))
    # 打印强连通分量个数
    print(f"  强连通分量数: {len(sccs)}")

    # 初始化环ID计数器，从1开始编号
    cycle_id_counter = 1
    # 初始化结果列表
    results = []
    # 用于去重：已经记录过的环集合不再重复记录
    seen_cycle_sets = set()

    # 遍历每个强连通分量
    for scc in sccs:
        # 强连通分量大小小于2不可能成环，跳过
        if len(scc) < 2:
            continue

        # 取出分量中所有节点
        sub_nodes = list(scc)
        # 提取子图
        sub_G = G.subgraph(sub_nodes).copy()

        try:
            # 使用simple_cycles算法找出子图中所有简单环
            cycles = list(nx.simple_cycles(sub_G))
        except Exception:
            # 算法异常，跳过该分量
            continue

        # 遍历找到的每个环
        for cycle in cycles:
            # 环长度小于2不可能成环，跳过
            if len(cycle) < 2:
                continue

            # 将环转换为不可变的frozenset用于去重判断
            cycle_set = frozenset(cycle)
            # 如果这个环已经被记录过，跳过
            if cycle_set in seen_cycle_sets:
                continue
            # 添加到已记录集合
            seen_cycle_sets.add(cycle_set)

            # 构造路径字符串，在末尾加上起点，形成闭环表示
            nodes_in_cycle = list(cycle) + [cycle[0]]
            path_str = "->".join(str(n) for n in nodes_in_cycle)
            # 构造客户ID逗号分隔字符串
            cust_ids_str = ",".join(str(n) for n in cycle)

            # 计算环中所有担保金额总和
            total_amt = 0.0
            # 遍历环中每条边
            for i in range(len(cycle)):
                # 当前节点u
                u = cycle[i]
                # 下一个节点v
                v = cycle[(i + 1) % len(cycle)]
                # 如果图中存在这条边
                if G.has_edge(u, v):
                    # 累加担保金额
                    total_amt += G[u][v].get('guar_amt', 0)

            # 根据环长度确定风险等级
            cycle_len = len(cycle)
            if cycle_len >= CYCLE_LENGTH_HIGH:
                # 长度大于等于5，高风险
                risk = "HIGH"
            elif cycle_len >= CYCLE_LENGTH_MEDIUM:
                # 长度大于等于3小于5，中风险
                risk = "MEDIUM"
            else:
                # 小于3为低风险
                risk = "LOW"

            # 将结果添加到结果列表
            results.append((
                cycle_id_counter, cycle_len, path_str, cust_ids_str,
                round(total_amt, 2), risk, detect_time
            ))
            # 环ID自增
            cycle_id_counter += 1

    # 打印找到的环数量
    print(f"  ✓ 检测到 {len(results)} 个担保环")
    # 返回结果列表
    return results


# 算法2：团伙检测，使用社区检测算法识别担保网络和交易网络中的团伙
def detect_gangs(guar_edges, trans_edges, cust_name: dict, detect_time: str):
    # 打印日志
    print("\n🔍 算法2: 团伙检测...")

    # 内部辅助函数：在给定图上运行社区检测算法，返回节点->社区ID的分区字典
    def _run_louvain(G: nx.Graph):
        # 如果图没有边，返回空字典
        if G.number_of_edges() == 0:
            return {}
        try:
            # 优先使用Louvain算法（ Leiden算法之前的经典社区发现算法 ）
            communities = nx.community.louvain_communities(G, seed=42)
        except Exception:
            # 如果Louvain不可用，尝试标签传播算法
            try:
                communities = list(nx.community.label_propagation_communities(G))
            except Exception:
                # 如果上述算法都不可用，退化为连通分量检测
                communities = list(nx.connected_components(G))

        # 构造分区字典：节点->社区ID
        partition = {}
        # 遍历每个社区，编号从0开始
        for com_id, com in enumerate(communities):
            # 遍历社区中每个节点
            for node in com:
                # 记录该节点所属社区ID
                partition[node] = com_id
        # 返回分区字典
        return partition

    # 构建担保网络无向图（团伙检测不考虑方向）
    G_guar = nx.Graph()
    # 遍历所有担保边添加到图中，边权重为担保金额
    for src, dst, guar_id, amt in guar_edges:
        G_guar.add_edge(src, dst, weight=amt)

    # 在担保图上运行社区检测
    guar_partition = _run_louvain(G_guar)
    # 按社区ID分组，每个社区对应一个团伙，保存成员列表
    guar_gangs = defaultdict(list)
    for node, gid in guar_partition.items():
        guar_gangs[gid].append(node)

    # 同样处理交易网络，构建无向图
    G_trans = nx.Graph()
    for src, dst, tid, amt in trans_edges:
        G_trans.add_edge(src, dst, weight=amt)

    # 在交易图上运行社区检测
    trans_partition = _run_louvain(G_trans)
    # 按社区分组
    trans_gangs = defaultdict(list)
    for node, gid in trans_partition.items():
        trans_gangs[gid].append(node)

    # 初始化团伙ID计数器
    gang_id_counter = 1
    # 初始化最终结果列表
    gang_results = []

    # 处理担保网络检测出的所有团伙
    for gid, members in guar_gangs.items():
        # 团伙成员小于2不算团伙，跳过
        if len(members) < 2:
            continue
        # 团伙大小即成员数量
        gang_size = len(members)
        # 遍历每个成员
        for m in members:
            # 根据团伙大小在所有团伙中的占比计算风险评分，越大风险越高
            risk_score = min(round((gang_size / max(1, len(guar_gangs))) * 0.8, 4), 1.0)
            # 添加结果
            gang_results.append((
                gang_id_counter, m, cust_name.get(m, ""),
                gang_size, "guarantee", risk_score, detect_time
            ))
        # 团伙ID自增
        gang_id_counter += 1

    # 同理处理交易网络检测出的团伙
    for gid, members in trans_gangs.items():
        if len(members) < 2:
            continue
        gang_size = len(members)
        for m in members:
            # 交易团伙权重稍低，乘以0.6
            risk_score = min(round((gang_size / max(1, len(trans_gangs))) * 0.6, 4), 1.0)
            gang_results.append((
                gang_id_counter, m, cust_name.get(m, ""),
                gang_size, "transaction", risk_score, detect_time
            ))
        gang_id_counter += 1

    # 打印检测到的团伙数量
    print(f"  ✓ 检测到 {gang_id_counter - 1} 个团伙")
    # 返回结果
    return gang_results


# 算法3：多头借贷检测，统计客户贷款笔数，超过阈值标记为风险
def detect_multi_head(borrows, cust_name: dict, cust_score: dict, detect_time: str):
    # 打印日志
    print("\n🔍 算法3: 多头借贷检测...")

    # 按客户ID分组，保存该客户所有贷款信息
    cust_loans = defaultdict(list)
    # 遍历所有借贷关系
    for cid, lid, amt, overdue, status in borrows:
        # 将当前贷款添加到对应客户列表
        cust_loans[cid].append((lid, amt, overdue, status))

    # 初始化结果列表
    results = []
    # 遍历每个客户及其贷款列表
    for cid, loans in cust_loans.items():
        # 获取客户贷款笔数
        loan_count = len(loans)
        # 如果贷款笔数小于阈值，不标记为多头借贷，跳过
        if loan_count < MULTI_HEAD_THRESHOLD:
            continue

        # 计算该客户所有贷款总额
        total_amt = sum(l[1] for l in loans)
        # 统计逾期贷款笔数
        overdue_count = sum(1 for l in loans if l[2] > 0)
        # 找出最大逾期天数
        max_overdue = max((l[2] for l in loans), default=0)

        # 根据贷款笔数和逾期情况确定风险等级
        if loan_count >= 10 or max_overdue > 90:
            # 贷款笔数超过10笔或最大逾期超过90天，高风险
            risk = "HIGH"
        elif loan_count >= 6 or max_overdue > 30:
            # 贷款笔数超过6笔或逾期超过30天，中风险
            risk = "MEDIUM"
        else:
            # 其他情况低风险
            risk = "LOW"

        # 添加结果到列表
        results.append((
            cid, cust_name.get(cid, ""), loan_count,
            round(total_amt, 2), overdue_count, max_overdue,
            risk, detect_time
        ))

    # 按贷款笔数降序排序，笔数多的排在前面
    results.sort(key=lambda x: x[2], reverse=True)
    # 打印结果数量
    print(f"  ✓ 检测到 {len(results)} 个多头借贷客户")
    # 返回结果列表
    return results


# 算法4：交易闭环检测，在交易网络图中找出所有闭合环路，此类环路可能代表资金空转洗钱
def detect_transaction_cycles(G: nx.DiGraph, detect_time: str):
    # 打印日志
    print("\n🔍 算法4: 交易闭环检测...")

    # 如果图中没有边，直接返回空列表
    if G.number_of_edges() == 0:
        print("  ⚠️ 无交易数据，跳过闭环检测")
        return []

    # 找出所有强连通分量
    sccs = list(nx.strongly_connected_components(G))
    # 打印分量数量
    print(f"  强连通分量数: {len(sccs)}")

    # 初始化环ID计数器
    cycle_id_counter = 1
    # 初始化结果列表
    results = []
    # 去重用的已见环集合
    seen_cycle_sets = set()

    # 遍历每个强连通分量
    for scc in sccs:
        # 分量大小小于2不可能成环，跳过
        if len(scc) < 2:
            continue

        # 取出分量中节点，提取子图
        sub_nodes = list(scc)
        sub_G = G.subgraph(sub_nodes).copy()

        try:
            # 找出子图中所有简单环
            cycles = list(nx.simple_cycles(sub_G))
        except Exception:
            # 异常跳过该分量
            continue

        # 遍历每个环
        for cycle in cycles:
            # 长度小于2跳过
            if len(cycle) < 2:
                continue

            # 去重处理
            cycle_set = frozenset(cycle)
            if cycle_set in seen_cycle_sets:
                continue
            seen_cycle_sets.add(cycle_set)

            # 构造路径字符串
            nodes_in_cycle = list(cycle) + [cycle[0]]
            path_str = "->".join(str(n) for n in nodes_in_cycle)

            # 计算闭环总交易金额
            total_amt = 0.0
            for i in range(len(cycle)):
                u = cycle[i]
                v = cycle[(i + 1) % len(cycle)]
                if G.has_edge(u, v):
                    total_amt += G[u][v].get('trans_amt', 0)

            # 根据闭环长度确定风险等级
            cycle_len = len(cycle)
            if cycle_len >= TRANS_CYCLE_LENGTH_HIGH:
                # 长度大于等于6，高风险
                risk = "HIGH"
            elif cycle_len >= TRANS_CYCLE_LENGTH_MEDIUM:
                # 大于等于4小于6，中风险
                risk = "MEDIUM"
            else:
                # 小于4，低风险
                risk = "LOW"

            # 添加结果到列表
            results.append((
                cycle_id_counter, cycle_len, path_str,
                round(total_amt, 2), risk, detect_time
            ))
            # 环ID自增
            cycle_id_counter += 1

    # 打印检测到的闭环数量
    print(f"  ✓ 检测到 {len(results)} 个交易闭环")
    # 返回结果列表
    return results


# 算法5：逾期风险传染检测，找出距离逾期节点较近的非逾期客户，这些客户有被传染违约的风险
def detect_overdue_contagion(G_combined: nx.DiGraph, overdue_custs: set,
                              cust_name: dict, detect_time: str):
    # 打印日志
    print("\n🔍 算法5: 逾期风险传染检测...")

    # 如果没有逾期客户或者图为空，直接返回空列表
    if not overdue_custs or G_combined.number_of_nodes() == 0:
        print("  ⚠️ 无逾期客户或图数据，跳过传染检测")
        return []

    # 获取所有节点集合
    all_nodes = set(G_combined.nodes())

    # 将有向图转换为无向图，计算最短路径时不考虑方向
    G_undirected = G_combined.to_undirected()

    # 初始化结果列表
    results = []
    # 遍历每个节点
    for node in all_nodes:
        # 如果该节点本身就是逾期客户，跳过（我们找的是被传染的）
        if node in overdue_custs:
            continue

        # 初始化到最近逾期节点的最短距离为无穷大
        min_dist = float('inf')
        # 遍历所有逾期节点
        for overdue_node in overdue_custs:
            # 如果逾期节点不在图中，跳过
            if overdue_node not in G_undirected:
                continue
            try:
                # 计算当前节点到该逾期节点的最短路径长度
                dist = nx.shortest_path_length(G_undirected, node, overdue_node)
                # 如果这个距离比当前记录的最小距离还小，更新最小距离
                if dist < min_dist:
                    min_dist = dist
            except nx.NetworkXNoPath:
                # 没有路径，继续下一个逾期节点
                continue

        # 如果最短距离超过阈值，说明传染风险很小，跳过
        if min_dist > OVERDUE_CONTAGION_DISTANCE:
            continue

        # 统计该节点邻居中逾期节点的数量：邻居是所有前驱和后继节点的并集
        neighbors = set(G_combined.predecessors(node)) | set(G_combined.successors(node))
        # 计算交集，得到逾期邻居集合
        overdue_neighbors = neighbors & overdue_custs
        # 逾期邻居数量
        overdue_neighbor_count = len(overdue_neighbors)

        # 计算该客户与逾期邻居之间的总关联金额敞口
        total_exposure = 0.0
        # 遍历每个逾期邻居
        for nb in overdue_neighbors:
            # 如果有从邻居到当前节点的边，加上边的金额
            if G_combined.has_edge(nb, node):
                total_exposure += G_combined[nb][node].get('amt', 0)
            # 如果有从当前节点到邻居的边，也加上金额
            if G_combined.has_edge(node, nb):
                total_exposure += G_combined[node][nb].get('amt', 0)

        # 根据距离确定风险等级，距离越近风险越高
        if min_dist == 1:
            # 直接相邻，高风险
            risk = "HIGH"
        elif min_dist == 2:
            # 距离为2，中风险
            risk = "MEDIUM"
        else:
            # 距离3，低风险
            risk = "LOW"

        # 添加结果到列表
        results.append((
            node, cust_name.get(node, ""), overdue_neighbor_count,
            round(total_exposure, 2), int(min_dist), risk, detect_time
        ))

    # 按距离升序排序，距离越近排在越前面
    results.sort(key=lambda x: x[4])
    # 打印结果数量
    print(f"  ✓ 检测到 {len(results)} 个受逾期传染风险的客户")
    # 返回结果列表
    return results


# 算法6：PageRank算法识别网络中关键节点，PageRank分值越高说明节点越重要，仅打印输出不写入表
def detect_pagerank_key_nodes(G_combined: nx.DiGraph, cust_name: dict,
                               cust_score: dict, top_n: int = 20):
    # 打印日志
    print("\n🔍 算法6: PageRank 关键节点识别...")

    # 如果图中没有节点，返回空字典
    if G_combined.number_of_nodes() == 0:
        print("  ⚠️ 图数据为空，跳过 PageRank")
        return {}

    # 运行PageRank算法，alpha阻尼系数设为0.85，迭代100次，计算每个节点PR分值
    pr = nx.pagerank(G_combined, alpha=0.85, max_iter=100)
    # 将PR结果按分值降序排序
    sorted_pr = sorted(pr.items(), key=lambda x: x[1], reverse=True)

    # 打印Top N结果
    print(f"  ✓ Top {min(top_n, len(sorted_pr))} PageRank 关键节点:")
    # 初始化结果字典
    result = {}
    # 遍历排序后的结果，取前Top N个
    for rank, (node, score) in enumerate(sorted_pr[:top_n], 1):
        # 获取客户名称
        name = cust_name.get(node, "?")
        # 获取征信评分
        cs = cust_score.get(node, 600)
        # 保存到结果字典
        result[node] = {"rank": rank, "score": round(score, 6), "name": name, "credit_score": cs}
        # 打印该行信息
        print(f"    #{rank}: cust_id={node}, name={name}, score={score:.6f}")

    # 返回结果字典
    return result


# ==================== 7、结果写入 GBase 各结果表 ====================

# 将担保环检测结果写入GBase
def write_guarantee_cycles(results: list):
    # 如果结果为空，打印提示返回
    if not results:
        print("  ⚠️ 无担保环结果，跳过写入")
        return
    # 清空旧结果
    truncate_result_table("risk_guarantee_cycle")
    # 批量插入新结果
    batch_insert("risk_guarantee_cycle", [
        "cycle_id", "cycle_length", "cycle_path", "cust_ids",
        "total_guar_amt", "risk_level", "detect_time"
    ], results)


# 将团伙检测结果写入GBase
def write_gangs(results: list):
    # 结果为空直接返回
    if not results:
        print("  ⚠️ 无团伙结果，跳过写入")
        return
    # 清空旧结果
    truncate_result_table("risk_gang_detect")
    # 批量插入
    batch_insert("risk_gang_detect", [
        "gang_id", "cust_id", "cust_name", "gang_size",
        "gang_type", "risk_score", "detect_time"
    ], results)


# 将多头借贷检测结果写入GBase
def write_multi_head(results: list):
    # 结果为空返回
    if not results:
        print("  ⚠️ 无多头借贷结果，跳过写入")
        return
    # 清空旧结果
    truncate_result_table("risk_multi_head")
    # 批量插入
    batch_insert("risk_multi_head", [
        "cust_id", "cust_name", "loan_count", "total_loan_amt",
        "overdue_loan_count", "max_overdue_days", "risk_level", "detect_time"
    ], results)


# 将交易闭环检测结果写入GBase
def write_trans_cycles(results: list):
    # 结果为空返回
    if not results:
        print("  ⚠️ 无交易闭环结果，跳过写入")
        return
    # 清空旧结果
    truncate_result_table("risk_trans_cycle")
    # 批量插入
    batch_insert("risk_trans_cycle", [
        "cycle_id", "cycle_length", "cycle_path",
        "total_trans_amt", "risk_level", "detect_time"
    ], results)


# 将逾期传染检测结果写入GBase
def write_overdue_contagion(results: list):
    # 结果为空返回
    if not results:
        print("  ⚠️ 无逾期传染结果，跳过写入")
        return
    # 清空旧结果
    truncate_result_table("risk_overdue_contagion")
    # 批量插入
    batch_insert("risk_overdue_contagion", [
        "cust_id", "cust_name", "overdue_neighbor_count",
        "total_exposure_amt", "distance_to_overdue", "risk_level", "detect_time"
    ], results)


# ==================== 8、主流程入口 ====================

# 主函数，程序入口
def main():
    # 打印程序欢迎横幅
    print("""
╔══════════════════════════════════════════════════════════════╗
║   TuGraph → NetworkX 金融风控分析 → GBase                     ║
║   担保环 · 团伙识别 · 多头借贷 · 交易闭环 · 逾期传染           ║
╚══════════════════════════════════════════════════════════════╝
""")

    # 获取当前检测时间，格式化字符串
    detect_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 步骤1: 确保 GBase 结果表存在 ----
    print("\n📋 步骤1: 准备 GBase 结果表...")
    # 调用函数创建结果表（如果不存在）
    ensure_result_tables()

    # ---- 步骤2: 连接 TuGraph ----
    print("\n🔗 步骤2: 连接 TuGraph...")
    # 创建TuGraph客户端对象，使用配置参数
    client = TuGraphClient(
        host=TUGRAPH_CFG['host'],
        port=TUGRAPH_CFG['rest_port'],
        user=TUGRAPH_CFG['user'],
        password=TUGRAPH_CFG['password'],
        graph_name=TUGRAPH_CFG['graph_name'],
        timeout=TUGRAPH_CFG['timeout']
    )

    # 尝试登录TuGraph
    if not client.login():
        # 登录失败打印错误并退出程序
        print("❌ 无法登录 TuGraph，请检查连接配置")
        sys.exit(1)

    # ---- 步骤3: 从 TuGraph 读取全部图数据 ----
    print("\n📥 步骤3: 从 TuGraph 读取图数据...")
    # 记录开始时间
    t0 = time.time()

    # 读取所有客户，得到名称字典和评分字典
    cust_name, cust_score = read_customers(client)
    # 如果读取到的客户为空，说明TuGraph中没有数据，提示用户并退出
    if not cust_name:
        print("❌ TuGraph 中无客户数据，请先运行 gbase_to_tugraph.py")
        sys.exit(1)

    # 读取担保边列表
    guar_edges = read_guarantees(client)
    # 读取交易边列表
    trans_edges = read_transactions(client)
    # 读取借贷关系列表
    borrows = read_borrows(client)
    # 读取逾期客户ID集合
    overdue_custs = read_overdue_customers(client)

    # 读取完成后关闭TuGraph客户端
    client.close()

    # 计算读取耗时
    elapsed_read = time.time() - t0
    # 打印读取耗时
    print(f"\n⏱️  数据读取耗时: {elapsed_read:.1f} 秒")

    # ---- 步骤4: 构建 NetworkX 图 ----
    print("\n🏗️  步骤4: 构建 NetworkX 图模型...")
    # 构建担保有向图
    G_guar = build_guarantee_graph(guar_edges)
    # 构建交易有向图
    G_trans = build_transaction_graph(trans_edges)
    # 构建担保和交易合并的复合有向图
    G_combined = build_combined_graph(guar_edges, trans_edges)

    # 打印各图的节点数和边数统计
    print(f"  担保图: {G_guar.number_of_nodes()} 节点, {G_guar.number_of_edges()} 边")
    print(f"  交易图: {G_trans.number_of_nodes()} 节点, {G_trans.number_of_edges()} 边")
    print(f"  复合图: {G_combined.number_of_nodes()} 节点, {G_combined.number_of_edges()} 边")

    # ---- 步骤5: 风控算法分析 ----
    # 打印分隔线
    print("\n" + "=" * 60)
    print("🔬 步骤5: 执行金融风控算法分析...")
    print("=" * 60)

    # 记录算法开始时间
    t1 = time.time()

    # 执行算法1：担保环检测，得到结果列表
    cycle_results = detect_guarantee_cycles(G_guar, cust_name, detect_time)

    # 执行算法2：团伙检测，得到结果列表
    gang_results = detect_gangs(guar_edges, trans_edges, cust_name, detect_time)

    # 执行算法3：多头借贷检测，得到结果列表
    multi_results = detect_multi_head(borrows, cust_name, cust_score, detect_time)

    # 执行算法4：交易闭环检测，得到结果列表
    trans_cycle_results = detect_transaction_cycles(G_trans, detect_time)

    # 执行算法5：逾期风险传染检测，得到结果列表
    contagion_results = detect_overdue_contagion(
        G_combined, overdue_custs, cust_name, detect_time
    )

    # 执行算法6：PageRank关键节点识别，仅打印结果不入库
    pr_result = detect_pagerank_key_nodes(G_combined, cust_name, cust_score)

    # 计算算法总耗时
    elapsed_algo = time.time() - t1
    # 打印算法耗时
    print(f"\n⏱️  算法分析耗时: {elapsed_algo:.1f} 秒")

    # ---- 步骤6: 结果写入 GBase ----
    # 打印分隔线
    print("\n" + "=" * 60)
    print("💾 步骤6: 结果写入 GBase...")
    print("=" * 60)

    # 依次将各算法结果写入对应的GBase表
    write_guarantee_cycles(cycle_results)
    write_gangs(gang_results)
    write_multi_head(multi_results)
    write_trans_cycles(trans_cycle_results)
    write_overdue_contagion(contagion_results)

    # ---- 汇总打印 ----
    # 计算从开始到结束的总耗时
    total_elapsed = time.time() - t0
    # 打印汇总信息
    print("\n" + "=" * 60)
    print("🎉 全部分析完成!")
    print(f"   担保环:     {len(cycle_results)} 个")
    print(f"   团伙成员:   {len(gang_results)} 个")
    print(f"   多头借贷:   {len(multi_results)} 个客户")
    print(f"   交易闭环:   {len(trans_cycle_results)} 个")
    print(f"   逾期传染:   {len(contagion_results)} 个客户")
    print(f"   PageRank:   {len(pr_result)} 个关键节点")
    print(f"   总耗时:     {total_elapsed:.1f} 秒")
    print("=" * 60)


# 如果该文件作为主程序运行，则调用main函数
if __name__ == "__main__":
    main()