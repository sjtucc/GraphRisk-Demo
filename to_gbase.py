import random
from datetime import datetime, timedelta
from faker import Faker
from GBaseConnector import connect

# ==========1、配置区（修改成你本机GBase信息）==========
DB_CFG = {
    "host": "110.42.238.172",
    "port": 5258,
    "user": "root",
    "password": "Chen641219!",
    "db": "fin_risk",
    "charset": "utf8"
}
fake = Faker("zh_CN")
BATCH_NUM = 200  # 每批次插入条数
CUST_COUNT = 500  # 生成客户总数
loan_id_start = 10000
guar_id_start = 20000
trans_id_start = 30000

# ==========2、数据库连接函数==========
def get_conn():
    return connect(**DB_CFG)

# ==========3、生成客户数据&入库==========
def insert_customer():
    conn = get_conn()
    cur = conn.cursor()
    cust_list = []
    cust_ids = []  # 保存所有客户ID，供贷款/担保/交易关联使用

    for cust_id in range(1, CUST_COUNT + 1):
        cust_type = random.randint(1, 2)
        name = fake.name()
        idcard = fake.ssn()
        phone = fake.phone_number()
        addr = fake.address()
        score = random.randint(300, 950)
        reg_date = fake.date_between(start_date="-5y", end_date="today")
        create_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = (cust_id, cust_type, name, idcard, phone, addr, score, reg_date, create_dt)
        cust_list.append(row)
        cust_ids.append(cust_id)

        # 批量提交
        if len(cust_list) >= BATCH_NUM:
            sql = """INSERT INTO cust_info(cust_id,cust_type,cust_name,id_card,phone,address,credit_score,register_date,create_time)
                     VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
            cur.executemany(sql, cust_list)
            conn.commit()
            cust_list.clear()
    # 剩余数据
    if cust_list:
        sql = """INSERT INTO cust_info(cust_id,cust_type,cust_name,id_card,phone,address,credit_score,register_date,create_time)
                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        cur.executemany(sql, cust_list)
        conn.commit()
    cur.close()
    conn.close()
    print(f"✅ 客户表插入完成，共{CUST_COUNT}条")
    return cust_ids

# ==========4、生成贷款数据（关联客户ID）==========
def insert_loan(cust_ids):
    global loan_id_start
    conn = get_conn()
    cur = conn.cursor()
    loan_list = []
    loan_ids = []
    loan_cnt = int(CUST_COUNT * 0.65)  # 65%客户有贷款

    for _ in range(loan_cnt):
        loan_id = loan_id_start
        loan_id_start += 1
        cid = random.choice(cust_ids)
        amt = round(random.uniform(1000, 2000000), 2)
        term = random.randint(3, 360)
        rate = round(random.uniform(0.03, 0.22), 4)
        ltype = random.randint(1, 4)
        s_date = fake.date_between("-3y", "today")
        d_date = s_date + timedelta(days=term)
        overdue = random.randint(0, 180) if random.random() < 0.2 else 0
        status = 1 if overdue > 0 else 0
        create_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = (loan_id, cid, amt, term, rate, ltype, s_date, d_date, overdue, status, create_dt)
        loan_list.append(row)
        loan_ids.append(loan_id)

        if len(loan_list) >= BATCH_NUM:
            sql = """INSERT INTO loan_info(loan_id,cust_id,loan_amt,loan_term,rate,loan_type,start_date,due_date,overdue_days,loan_status,create_time)
                     VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
            cur.executemany(sql, loan_list)
            conn.commit()
            loan_list.clear()
    if loan_list:
        sql = """INSERT INTO loan_info(loan_id,cust_id,loan_amt,loan_term,rate,loan_type,start_date,due_date,overdue_days,loan_status,create_time)
                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        cur.executemany(sql, loan_list)
        conn.commit()
    cur.close()
    conn.close()
    print(f"✅ 贷款表插入完成，共{loan_cnt}条")
    return loan_ids

# ==========5、担保数据（关联贷款+客户）==========
def insert_guarantee(cust_ids, loan_ids):
    global guar_id_start
    conn = get_conn()
    cur = conn.cursor()
    guar_list = []
    guar_cnt = int(len(loan_ids)*0.4)  # 40%贷款带担保

    for _ in range(guar_cnt):
        guar_id = guar_id_start
        guar_id_start +=1
        lid = random.choice(loan_ids)
        guar_cid = random.choice(cust_ids)
        borrow_cid = random.choice(cust_ids)
        g_amt = round(random.uniform(5000,3000000),2)
        g_type = random.randint(1,3)
        s_date = fake.date_between("-3y","today")
        e_date = s_date + timedelta(days=random.randint(180,2000))
        create_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = (guar_id,lid,guar_cid,borrow_cid,g_amt,g_type,s_date,e_date,create_dt)
        guar_list.append(row)

        if len(guar_list)>=BATCH_NUM:
            sql = """INSERT INTO guarantee_info(guar_id,loan_id,guar_cust_id,borrow_cust_id,guar_amt,guar_type,valid_start,valid_end,create_time)
                     VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
            cur.executemany(sql, guar_list)
            conn.commit()
            guar_list.clear()
    if guar_list:
        sql = """INSERT INTO guarantee_info(guar_id,loan_id,guar_cust_id,borrow_cust_id,guar_amt,guar_type,valid_start,valid_end,create_time)
                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        cur.executemany(sql, guar_list)
        conn.commit()
    cur.close()
    conn.close()
    print(f"✅ 担保表插入完成，共{guar_cnt}条")

# ==========6、转账交易数据（转出/转入客户）==========
def insert_trans(cust_ids):
    global trans_id_start
    conn = get_conn()
    cur = conn.cursor()
    trans_list = []
    trans_cnt = CUST_COUNT * 8

    for _ in range(trans_cnt):
        tid = trans_id_start
        trans_id_start +=1
        out_cid = random.choice(cust_ids)
        in_cid = random.choice(cust_ids)
        while out_cid == in_cid:
            in_cid = random.choice(cust_ids)
        tamt = round(random.uniform(1,500000),2)
        ttype = random.randint(1,5)
        tdt = fake.date_time_between("-2y", "now")
        remark = random.choice(["还款","拆借","日常转账","货款","投资回款",""])
        create_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = (tid, out_cid, in_cid, tamt, ttype, tdt, remark, create_dt)
        trans_list.append(row)

        if len(trans_list)>=BATCH_NUM:
            sql = """INSERT INTO trans_info(trans_id,out_cust_id,in_cust_id,trans_amt,trans_type,trans_time,remark,create_time)
                     VALUES(%s,%s,%s,%s,%s,%s,%s,%s)"""
            cur.executemany(sql, trans_list)
            conn.commit()
            trans_list.clear()
    if trans_list:
        sql = """INSERT INTO trans_info(trans_id,out_cust_id,in_cust_id,trans_amt,trans_type,trans_time,remark,create_time)
                 VALUES(%s,%s,%s,%s,%s,%s,%s,%s)"""
        cur.executemany(sql, trans_list)
        conn.commit()
    cur.close()
    conn.close()
    print(f"✅ 交易表插入完成，共{trans_cnt}条")

# ==========主入口==========
if __name__ == "__main__":
    cust_id_list = insert_customer()
    loan_id_list = insert_loan(cust_id_list)
    insert_guarantee(cust_id_list, loan_id_list)
    insert_trans(cust_id_list)
    print("=====全部数据生成入库完毕=====")