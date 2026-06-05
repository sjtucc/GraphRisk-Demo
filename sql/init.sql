-- 1.创建数据库，单独执行
CREATE DATABASE IF NOT EXISTS fin_risk CHARSET=utf8;
USE fin_risk;

-- ①客户表：客户基础信息表
CREATE TABLE "cust_info" (
  "cust_id" bigint(20) NOT NULL COMMENT '客户唯一ID',
  "cust_type" tinyint(4) DEFAULT NULL COMMENT '客户类型：1个人 2企业',
  "cust_name" varchar(64) NOT NULL COMMENT '客户名称',
  "id_card" varchar(32) DEFAULT NULL COMMENT '身份证号/统一社会信用代码',
  "phone" varchar(20) DEFAULT NULL COMMENT '联系电话',
  "address" varchar(256) DEFAULT NULL COMMENT '居住/注册地址',
  "credit_score" int(11) DEFAULT NULL COMMENT '征信评分 300-950',
  "register_date" date DEFAULT NULL COMMENT '开户/注册日期',
  "create_time" datetime DEFAULT NULL COMMENT '数据创建时间',
  PRIMARY KEY ("cust_id"),
  KEY "idx_cust" ("cust_id") USING HASH GLOBAL
) ENGINE=EXPRESS DEFAULT CHARSET=utf8 TABLESPACE='sys_tablespace' COMMENT='客户基础信息表';

-- ②贷款表：贷款业务明细表
CREATE TABLE "loan_info" (
  "loan_id" bigint(20) NOT NULL COMMENT '贷款唯一编号',
  "cust_id" bigint(20) NOT NULL COMMENT '借款人客户ID',
  "loan_amt" decimal(18,2) NOT NULL COMMENT '贷款金额',
  "loan_term" smallint(6) DEFAULT NULL COMMENT '贷款期限（月）',
  "rate" decimal(6,4) DEFAULT NULL COMMENT '年化利率',
  "loan_type" tinyint(4) DEFAULT NULL COMMENT '贷款类型：1经营贷 2消费贷 3抵押贷',
  "start_date" date DEFAULT NULL COMMENT '放款日期',
  "due_date" date DEFAULT NULL COMMENT '到期日期',
  "overdue_days" int(11) DEFAULT '0' COMMENT '逾期天数',
  "loan_status" tinyint(4) DEFAULT NULL COMMENT '贷款状态：0正常 1逾期 2结清 3坏账',
  "create_time" datetime DEFAULT NULL COMMENT '数据创建时间',
  PRIMARY KEY ("loan_id"),
  KEY "idx_cust_loan" ("cust_id") USING HASH GLOBAL
) ENGINE=EXPRESS DEFAULT CHARSET=utf8 TABLESPACE='sys_tablespace' COMMENT='贷款业务明细表';

-- ③担保表：担保关系表（图数据库核心边数据）
CREATE TABLE "guarantee_info" (
  "guar_id" bigint(20) NOT NULL COMMENT '担保记录ID',
  "loan_id" bigint(20) NOT NULL COMMENT '被担保的贷款ID',
  "guar_cust_id" bigint(20) NOT NULL COMMENT '担保人客户ID',
  "borrow_cust_id" bigint(20) NOT NULL COMMENT '被担保人（借款人）ID',
  "guar_amt" decimal(18,2) NOT NULL COMMENT '担保金额',
  "guar_type" tinyint(4) DEFAULT NULL COMMENT '担保类型：1连带担保 2一般担保',
  "valid_start" date DEFAULT NULL COMMENT '担保生效日期',
  "valid_end" date DEFAULT NULL COMMENT '担保到期日期',
  "create_time" datetime DEFAULT NULL COMMENT '数据创建时间',
  PRIMARY KEY ("guar_id"),
  KEY "idx_loan" ("loan_id") USING HASH GLOBAL,
  KEY "idx_guar" ("guar_cust_id") USING HASH GLOBAL,
  KEY "idx_borrow" ("borrow_cust_id") USING HASH GLOBAL
) ENGINE=EXPRESS DEFAULT CHARSET=utf8 TABLESPACE='sys_tablespace' COMMENT='担保关系表';

-- ④交易表：客户资金交易流水表
CREATE TABLE "trans_info" (
  "trans_id" bigint(20) NOT NULL COMMENT '交易流水号',
  "out_cust_id" bigint(20) NOT NULL COMMENT '转出方客户ID',
  "in_cust_id" bigint(20) NOT NULL COMMENT '转入方客户ID',
  "trans_amt" decimal(18,2) NOT NULL COMMENT '交易金额',
  "trans_type" tinyint(4) DEFAULT NULL COMMENT '交易类型：1放款 2还款 3转账 4代收代付',
  "trans_time" datetime DEFAULT NULL COMMENT '交易发生时间',
  "remark" varchar(256) DEFAULT NULL COMMENT '交易备注',
  "create_time" datetime DEFAULT NULL COMMENT '数据创建时间',
  PRIMARY KEY ("trans_id"),
  KEY "idx_out" ("out_cust_id") USING HASH GLOBAL,
  KEY "idx_in" ("in_cust_id") USING HASH GLOBAL
) ENGINE=EXPRESS DEFAULT CHARSET=utf8 TABLESPACE='sys_tablespace' COMMENT='客户资金交易流水表';