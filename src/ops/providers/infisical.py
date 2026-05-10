import os
import requests

class InfisicalProvider:
    def __init__(self, client_id, client_secret, org_id):
        self.client_id = client_id
        self.client_secret = client_secret
        self.org_id = org_id
        self.base_url = "https://app.infisical.com/api/v1"
        self.token = self._authenticate()

    def _authenticate(self):
        # Simple authentication flow implementation
        payload = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret
        }
        response = requests.post(f"{self.base_url}/auth/login", json=payload)
        response.raise_for_status()
        return response.json().get("token")

    def get_secret(self, secret_path: str, environment: str = "dev"):
        headers = {"Authorization": f"Bearer {self.token}"}
        params = {"secretPath": secret_path, "env": environment}
        response = requests.get(f"{self.base_url}/secret", headers=headers, params=params)
        response.raise_for_status()
        return response.json().get("secretValue")

    def get_secrets(self, folder_path: str, environment: str = "dev"):
        headers = {"Authorization": f"Bearer {self.token}"}
        params = {"folderPath": folder_path, "env": environment}
        response = requests.get(f"{self.base_url}/secrets", headers=headers, params=params)
        response.raise_for_status()
        return response.json().get("secrets", [])
