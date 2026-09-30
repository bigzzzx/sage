# SAGE 部署指南

## 一、上传代码到 GitHub

### 1. 本地初始化 Git（如果还没有）

```bash
cd "c:\Users\0856\Desktop\code\AI Hackathon"
git init
git add -A
git commit -m "initial commit"
```

### 2. GitHub 创建仓库

1. 登录 https://github.com
2. 点击右上角 "+" → "New repository"
3. 仓库名：`sage`（或你喜欢的名字）
4. 选 Private（内部项目建议私有）
5. 不要勾选"Initialize with README"（本地已有代码）
6. 点 "Create repository"

### 3. 推送到 GitHub

```bash
git remote add origin https://github.com/<你的用户名>/sage.git
git branch -M main
git push -u origin main
```

> 如果提示输入密码，GitHub 现在要求用 Personal Access Token（不是密码）。
> 去 GitHub → Settings → Developer settings → Personal access tokens → Generate new token

---

## 二、EC2 环境准备

### 1. EC2 实例要求

| 配置 | 建议 |
|---|---|
| AMI | Amazon Linux 2023 |
| 实例类型 | t3.medium 或以上（2 vCPU / 4 GB RAM） |
| 磁盘 | 20 GB gp3 |
| 安全组入站 | 22(SSH) / 3000(前端) / 8000(后端) |
| VPC | 需要和内部 LLM ELB 在同一 VPC（或有路由可达） |

### 2. 连接 EC2

```bash
ssh -i your-key.pem ec2-user@<EC2公网IP>
```

### 3. 安装基础依赖

```bash
# 更新系统
sudo yum update -y

# 安装 Python 3.12
sudo yum install python3.12 python3.12-pip python3.12-devel git -y

# 安装 Node.js 20
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo yum install nodejs -y

# 验证
python3.12 --version
node --version
npm --version
```

---

## 三、部署代码

### 1. 克隆代码

```bash
cd ~
git clone https://github.com/<你的用户名>/sage.git
cd sage
```

### 2. 后端部署

```bash
cd backend

# 创建虚拟环境
python3.12 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 创建 .env 配置文件
cat > .env << 'EOF'
LLM_PROVIDER=openai
LLM_API_KEY=<set-your-secret-in-the-server-environment>
LLM_BASE_URL=https://your-openai-compatible-endpoint.example/v1
LLM_MODEL=Qwen3.6-27B
APP_ENV=production
EOF

# 启动后端（后台运行）
nohup python3.12 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > ../logs/backend.log 2>&1 &

# 验证
curl http://localhost:8000/health
```

### 3. 前端部署

```bash
cd ~/sage/frontend

# 安装依赖
npm install

# 配置后端地址（生产环境）
echo "NEXT_PUBLIC_API_BASE=http://<EC2公网IP>:8000" > .env.local

# 构建生产版本
npm run build

# 启动前端（后台运行）
nohup npm start > ../logs/frontend.log 2>&1 &

# 验证
curl http://localhost:3000
```

### 4. 创建日志目录

```bash
mkdir -p ~/sage/logs
```

---

## 四、使用 systemd 管理进程（推荐）

用 systemd 可以让服务开机自启、崩溃自动重启。

### 后端 service

```bash
sudo tee /etc/systemd/system/sage-backend.service << 'EOF'
[Unit]
Description=SAGE Backend API
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/sage/backend
Environment=PATH=/home/ec2-user/sage/backend/venv/bin:/usr/bin
ExecStart=/home/ec2-user/sage/backend/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable sage-backend
sudo systemctl start sage-backend
sudo systemctl status sage-backend
```

### 前端 service

```bash
sudo tee /etc/systemd/system/sage-frontend.service << 'EOF'
[Unit]
Description=SAGE Frontend (Next.js)
After=network.target

[Service]
Type=simple
User=ec2-user
WorkingDirectory=/home/ec2-user/sage/frontend
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=5
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable sage-frontend
sudo systemctl start sage-frontend
sudo systemctl status sage-frontend
```

### 常用命令

```bash
# 查看日志
sudo journalctl -u sage-backend -f
sudo journalctl -u sage-frontend -f

# 重启
sudo systemctl restart sage-backend
sudo systemctl restart sage-frontend

# 停止
sudo systemctl stop sage-backend
sudo systemctl stop sage-frontend
```

---

## 五、访问

- 前端：`http://<EC2公网IP>:3000`
- 后端 API：`http://<EC2公网IP>:8000/docs`
- 登录账号：由部署者使用 `python -m app.cli create-admin --username <管理员名>` 显式创建，再通过管理员页面添加成员；仓库不提供默认密码。

---

## 六、更新代码

```bash
cd ~/sage
git pull origin main

# 后端有改动
cd backend
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart sage-backend

# 前端有改动
cd ~/sage/frontend
npm install
npm run build
sudo systemctl restart sage-frontend
```

---

## 七、注意事项

| 项目 | 说明 |
|---|---|
| `.env` 文件 | 不要推到 Git（已在 .gitignore），EC2 上手动创建 |
| `sage.db` | SQLite 数据库文件，启动时自动创建，不推到 Git |
| `node_modules/` | 不推到 Git，EC2 上 `npm install` 重新装 |
| LLM 网络 | EC2 必须能访问内部 ELB 地址（同 VPC 或有路由） |
| 安全组 | 至少开放 22/3000/8000 端口 |
| 域名（可选） | 后续可以用 ALB + Route53 绑定域名，走 HTTPS |

---

## 八、可选：用 Nginx 反向代理（生产推荐）

```bash
sudo yum install nginx -y

sudo tee /etc/nginx/conf.d/sage.conf << 'EOF'
server {
    listen 80;
    server_name _;

    # 前端
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
    }

    # 后端 API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

sudo systemctl enable nginx
sudo systemctl start nginx
```

这样访问 `http://<EC2公网IP>` 就能用（80 端口，前后端统一入口）。
前端的 `NEXT_PUBLIC_API_BASE` 改为空字符串（因为 nginx 会转发 /api/ 到后端）。
