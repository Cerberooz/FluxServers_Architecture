# Flux node uptime reporter

Current Wings releases do not expose the host operating-system uptime through
their system-information endpoint. This small, separate systemd component reads
`/proc/uptime` once a minute and reports the value to FluidPanel.

It uses the node's existing Wings `token_id` and `token` from
`/etc/pterodactyl/config.yml`; it does not create, store, or expose another
credential. The Panel's daemon authentication middleware resolves that token to
the calling node, so a node can update only its own uptime.

## Install on each Wings node

Copy the three files in this directory onto the node, then run:

```bash
sudo install -m 0755 flux-node-uptime-reporter /usr/local/bin/flux-node-uptime-reporter
sudo install -m 0644 flux-node-uptime.service /etc/systemd/system/flux-node-uptime.service
sudo install -m 0644 flux-node-uptime.timer /etc/systemd/system/flux-node-uptime.timer
sudo systemctl daemon-reload
sudo systemctl enable --now flux-node-uptime.timer
sudo systemctl start flux-node-uptime.service
```

Verify it with:

```bash
sudo systemctl status flux-node-uptime.timer
sudo journalctl -u flux-node-uptime.service -n 20 --no-pager
```

The Panel must be deployed and migrated before the first report:

```bash
sudo docker compose -f compose.control.yaml exec panel php artisan migrate --force
```

If the report cannot reach the Panel, Wings and game-server operation are not
affected; the Panel simply displays **Unavailable** until a successful report
arrives.
