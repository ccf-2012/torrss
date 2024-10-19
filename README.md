# TORRSS
* a RSS client for limite storage machine
* 适用于小盘机刷流。在添加种子时，根据磁盘剩余空间进行删种，支持 qBittorrent


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
