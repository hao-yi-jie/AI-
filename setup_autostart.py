# -*- coding: utf-8 -*-
"""配置 Startup 自启动：写 GBK 编码 bat + 移除失效 VBS"""
import os

startup = os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows',
                       'Start Menu', 'Programs', 'Startup')
project = r'C:\Users\RKBL\WorkBuddy\股票看板工作台\csi300_workbench'

content = '@echo off\r\ncall "' + project + '\\autostart.bat"\r\n'
bat_path = os.path.join(startup, 'CSI300Workbench-autostart.bat')
with open(bat_path, 'w', encoding='gbk', newline='') as f:
    f.write(content)
print('written bat:', bat_path)

vbs = os.path.join(startup, 'CSI300Workbench-autostart.vbs')
if os.path.exists(vbs):
    os.remove(vbs)
    print('vbs removed')
print('startup folder:', os.listdir(startup))
