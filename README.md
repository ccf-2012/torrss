# TORRSS
* a RSS client for limite storage machine
* 适用于小盘机刷流。在添加种子时，根据磁盘剩余空间进行删种，支持 qBittorrent

## 流程逻辑
* 由 qb 取得磁盘剩余空间 size_storage_space
* 根据设置的条件从 rss 中逐一取种子
  1. 设准备新添加的种子大小为 size_new_torrent
  2. 计算 qb 中当前所有正在下载的种子的剩余体积 size_left_to_complete
  3. 如果 size_storage_space - size_left_to_complete > size_new_torrent 则直接加种
  4. 否则，对 qb 中已完成种子，以 seeding_time 排序，逐个：
     1. 假设删除种子，size_storage_space 增加种子完成的大小
     2. 重新判断 size_storage_space - size_left_to_complete > size_new_torrent，成功则真实删种，并加种退出
     3. 否则继续，直至所有已完成种子都假设删光
     4. 如果假设所有已完成种子删光仍不够空间，则不进行真实删种，也不加种，Skip退出

## Install
1. if the system don't have `venv`, install it.
```sh 
apt install python3.11-venv
```

2. pull the code
```sh
git clone https://github.com/ccf-2012/torrss.git
```


3. Create a venv and activate it.
```sh
python3 -m venv torss
torss/bin/activate
```

4. install the requirements
```sh
pip install -r requirements.txt
```


## Generate a password 
```sh
python app.py -G
```


## Run the app
```sh
python app.py
```
