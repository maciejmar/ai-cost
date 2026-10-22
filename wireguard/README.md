# WireGuard — Instrukcja konfiguracji

## Generowanie kluczy (na każdej maszynie osobno)

```bash
# Wygeneruj parę kluczy
wg genkey | tee private.key | wg pubkey > public.key

# Wyświetl
cat private.key   # → wpisz jako PrivateKey w [Interface]
cat public.key    # → wpisz jako PublicKey w [Peer] na innych maszynach
```

## Kolejność konfiguracji

1. **VPS OVH** — `wg0-ovh.conf` → uzupełnij OVH_PRIVATE_KEY + klucze publiczne webaby i GPU
2. **Webaby** — `wg0-webaby.conf` → uzupełnij WEBABY_PRIVATE_KEY + klucz publiczny OVH + IP OVH
3. **GPU** — `wg0-gpu.conf` → uzupełnij GPU_PRIVATE_KEY + klucz publiczny OVH + IP OVH

## Instalacja (Ubuntu)

```bash
sudo apt install wireguard
sudo cp wg0-XXX.conf /etc/wireguard/wg0.conf
sudo chmod 600 /etc/wireguard/wg0.conf
sudo wg-quick up wg0
sudo systemctl enable wg-quick@wg0
```

## Test połączenia

```bash
# Z OVH ping do webaby i GPU:
ping 10.10.0.2
ping 10.10.0.3

# Status tunelu:
sudo wg show
```

## Adresy WireGuard

| Maszyna   | WireGuard IP | Rola                        |
|-----------|--------------|-----------------------------|
| VPS OVH   | 10.10.0.1    | Brama publiczna             |
| Webaby    | 10.10.0.2    | Agenty + bazy + monitoring  |
| GPU       | 10.10.0.3    | Ollama + LiteLLM + Langfuse |
