# upload_ec2.py

import paramiko
from scp import SCPClient
import re
import os
import requests

class Uploader:
    def __init__(self):
        self.hostname = '3.81.87.215'
        self.username = 'ubuntu'
        self.pem_key_path = 'MainSer.pem'
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        key = paramiko.Ed25519Key.from_private_key_file(self.pem_key_path)
        self.ssh.connect(self.hostname, username=self.username, pkey=key)

    def sanitize_directory_name(self, name: str) -> str:
        return re.sub(r"[\/\0\*\?\~\&\$\|><\;\'\"\\\[\]\(\)]", "_", name).replace(" ", "_").strip(". ")

    def upload_to_ec2(self, local_dir: str):
        with SCPClient(self.ssh.get_transport()) as scp:
            song_name = self.sanitize_directory_name(local_dir.split("/")[-1])
            print(f"🚀 Uploading to EC2: {song_name}")

            self.ssh.exec_command(f"mkdir -p /home/ubuntu/Spleeterv2/back/DownloadScr/Library/{song_name}")
            remote_path = f"/home/ubuntu/Spleeterv2/back/DownloadScr/Library/{song_name}/"

            scp.put(local_dir, recursive=True, remote_path=remote_path)

            payload = {
                "Title": song_name,
                "Fl": f"Library/{song_name}/",
                "Author": "",
                "Genre": "",
                "BPM": "",
                "MusicKey": "",
                "IsPremium": 1
            }

            res = requests.post(
                "https://database.samplesplit.com/insert_music",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            print(f"✅ EC2 upload done. DB response: {res.status_code}")
