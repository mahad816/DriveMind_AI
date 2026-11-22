# Depot systems runbook

This runbook covers the seven systems that run in every Marrowdale depot. The on-call engineer uses `mfc-ctl` for all of them. The transport management system listens on port 7410.


## Transport management system (tms)

The transport management system runs as the service `tms` and listens on port 7410. Its owner is the dispatcher.

### Start and stop

```
mfc-ctl restart tms --depot KY
mfc-ctl status tms
```

A restart takes about 20 seconds. Use the `--depot` flag with the two-letter depot code; without it the command refuses to run.

### Health checks

The health endpoint must answer within 15 seconds. If it fails 6 times in a row the monitor pages the on-call engineer. The service queue is healthy below 700 messages, and the disk alert fires at 86 percent usage.

### Known failures

- Stuck queue: the tms queue stops draining after a network drop; restart the service.
- Clock drift: a drift of more than 6 seconds makes tms reject requests; resync the clock first.
- Full disk: clear the spool directory, then restart tms.

### Capacity limits

The tms service is sized for 2100 requests per minute per depot. Above 2800 requests per minute it starts to refuse new work, and the dispatcher is paged after 15 seconds of refusals.

### Maintenance windows

Planned work on tms happens on Tuesday between 02:00 and 04:00. The dispatcher announces it 6 days ahead.

### Backups

A snapshot of tms is taken every 4 hours and kept for 14 days. A restore takes about 40 minutes and is started with `mfc-ctl restore tms --depot KY --snapshot latest`.

### Escalation

If a restart does not help within 20 minutes, the on-call engineer calls the dispatcher and then the depot manager.


## Loading dock scheduler (dock-scheduler)

The loading dock scheduler runs as the service `dock-scheduler` and listens on port 7420. Its owner is the yard planner.

### Start and stop

```
mfc-ctl restart dock-scheduler --depot KY
mfc-ctl status dock-scheduler
```

A restart takes about 20 seconds. Use the `--depot` flag with the two-letter depot code; without it the command refuses to run.

### Health checks

The health endpoint must answer within 10 seconds. If it fails 3 times in a row the monitor pages the on-call engineer. The service queue is healthy below 850 messages, and the disk alert fires at 82 percent usage.

### Known failures

- Stuck queue: the dock-scheduler queue stops draining after a network drop; restart the service.
- Clock drift: a drift of more than 3 seconds makes dock-scheduler reject requests; resync the clock first.
- Full disk: clear the spool directory, then restart dock-scheduler.

### Capacity limits

The dock-scheduler service is sized for 2550 requests per minute per depot. Above 3400 requests per minute it starts to refuse new work, and the yard planner is paged after 10 seconds of refusals.

### Maintenance windows

Planned work on dock-scheduler happens on Wednesday between 02:00 and 05:00. The yard planner announces it 3 days ahead.

### Backups

A snapshot of dock-scheduler is taken every 6 hours and kept for 21 days. A restore takes about 40 minutes and is started with `mfc-ctl restore dock-scheduler --depot KY --snapshot latest`.

### Escalation

If a restart does not help within 20 minutes, the on-call engineer calls the yard planner and then the depot manager.


## Vehicle telemetry gateway (telemetry-gateway)

The vehicle telemetry gateway runs as the service `telemetry-gateway` and listens on port 7430. Its owner is the fleet engineer.

### Start and stop

```
mfc-ctl restart telemetry-gateway --depot KY
mfc-ctl status telemetry-gateway
```

A restart takes about 25 seconds. Use the `--depot` flag with the two-letter depot code; without it the command refuses to run.

### Health checks

The health endpoint must answer within 35 seconds. If it fails 4 times in a row the monitor pages the on-call engineer. The service queue is healthy below 550 messages, and the disk alert fires at 76 percent usage.

### Known failures

- Stuck queue: the telemetry-gateway queue stops draining after a network drop; restart the service.
- Clock drift: a drift of more than 4 seconds makes telemetry-gateway reject requests; resync the clock first.
- Full disk: clear the spool directory, then restart telemetry-gateway.

### Capacity limits

The telemetry-gateway service is sized for 1650 requests per minute per depot. Above 2200 requests per minute it starts to refuse new work, and the fleet engineer is paged after 35 seconds of refusals.

### Maintenance windows

Planned work on telemetry-gateway happens on Tuesday between 03:00 and 04:00. The fleet engineer announces it 4 days ahead.

### Backups

A snapshot of telemetry-gateway is taken every 2 hours and kept for 35 days. A restore takes about 50 minutes and is started with `mfc-ctl restore telemetry-gateway --depot KY --snapshot latest`.

### Escalation

If a restart does not help within 25 minutes, the on-call engineer calls the fleet engineer and then the depot manager.


## Pallet label printing service (label-service)

The pallet label printing service runs as the service `label-service` and listens on port 7440. Its owner is the warehouse lead.

### Start and stop

```
mfc-ctl restart label-service --depot KY
mfc-ctl status label-service
```

A restart takes about 10 seconds. Use the `--depot` flag with the two-letter depot code; without it the command refuses to run.

### Health checks

The health endpoint must answer within 25 seconds. If it fails 5 times in a row the monitor pages the on-call engineer. The service queue is healthy below 800 messages, and the disk alert fires at 88 percent usage.

### Known failures

- Stuck queue: the label-service queue stops draining after a network drop; restart the service.
- Clock drift: a drift of more than 5 seconds makes label-service reject requests; resync the clock first.
- Full disk: clear the spool directory, then restart label-service.

### Capacity limits

The label-service service is sized for 2400 requests per minute per depot. Above 3200 requests per minute it starts to refuse new work, and the warehouse lead is paged after 25 seconds of refusals.

### Maintenance windows

Planned work on label-service happens on Wednesday between 01:00 and 04:00. The warehouse lead announces it 5 days ahead.

### Backups

A snapshot of label-service is taken every 10 hours and kept for 21 days. A restore takes about 20 minutes and is started with `mfc-ctl restore label-service --depot KY --snapshot latest`.

### Escalation

If a restart does not help within 10 minutes, the on-call engineer calls the warehouse lead and then the depot manager.


## Cold chain temperature logger (temp-logger)

The cold chain temperature logger runs as the service `temp-logger` and listens on port 7450. Its owner is the cold chain technician.

### Start and stop

```
mfc-ctl restart temp-logger --depot KY
mfc-ctl status temp-logger
```

A restart takes about 45 seconds. Use the `--depot` flag with the two-letter depot code; without it the command refuses to run.

### Health checks

The health endpoint must answer within 10 seconds. If it fails 4 times in a row the monitor pages the on-call engineer. The service queue is healthy below 600 messages, and the disk alert fires at 66 percent usage.

### Known failures

- Stuck queue: the temp-logger queue stops draining after a network drop; restart the service.
- Clock drift: a drift of more than 4 seconds makes temp-logger reject requests; resync the clock first.
- Full disk: clear the spool directory, then restart temp-logger.

### Capacity limits

The temp-logger service is sized for 1800 requests per minute per depot. Above 2400 requests per minute it starts to refuse new work, and the cold chain technician is paged after 10 seconds of refusals.

### Maintenance windows

Planned work on temp-logger happens on Wednesday between 02:00 and 05:00. The cold chain technician announces it 4 days ahead.

### Backups

A snapshot of temp-logger is taken every 2 hours and kept for 14 days. A restore takes about 90 minutes and is started with `mfc-ctl restore temp-logger --depot KY --snapshot latest`.

### Escalation

If a restart does not help within 45 minutes, the on-call engineer calls the cold chain technician and then the depot manager.


## Route planning service (route-planner)

The route planning service runs as the service `route-planner` and listens on port 7460. Its owner is the dispatcher.

### Start and stop

```
mfc-ctl restart route-planner --depot KY
mfc-ctl status route-planner
```

A restart takes about 15 seconds. Use the `--depot` flag with the two-letter depot code; without it the command refuses to run.

### Health checks

The health endpoint must answer within 5 seconds. If it fails 5 times in a row the monitor pages the on-call engineer. The service queue is healthy below 850 messages, and the disk alert fires at 86 percent usage.

### Known failures

- Stuck queue: the route-planner queue stops draining after a network drop; restart the service.
- Clock drift: a drift of more than 5 seconds makes route-planner reject requests; resync the clock first.
- Full disk: clear the spool directory, then restart route-planner.

### Capacity limits

The route-planner service is sized for 2550 requests per minute per depot. Above 3400 requests per minute it starts to refuse new work, and the dispatcher is paged after 5 seconds of refusals.

### Maintenance windows

Planned work on route-planner happens on Tuesday between 01:00 and 04:00. The dispatcher announces it 5 days ahead.

### Backups

A snapshot of route-planner is taken every 10 hours and kept for 35 days. A restore takes about 30 minutes and is started with `mfc-ctl restore route-planner --depot KY --snapshot latest`.

### Escalation

If a restart does not help within 15 minutes, the on-call engineer calls the dispatcher and then the depot manager.


## Proof of delivery sync (pod-sync)

The proof of delivery sync runs as the service `pod-sync` and listens on port 7470. Its owner is the customer desk.

### Start and stop

```
mfc-ctl restart pod-sync --depot KY
mfc-ctl status pod-sync
```

A restart takes about 30 seconds. Use the `--depot` flag with the two-letter depot code; without it the command refuses to run.

### Health checks

The health endpoint must answer within 25 seconds. If it fails 5 times in a row the monitor pages the on-call engineer. The service queue is healthy below 500 messages, and the disk alert fires at 66 percent usage.

### Known failures

- Stuck queue: the pod-sync queue stops draining after a network drop; restart the service.
- Clock drift: a drift of more than 5 seconds makes pod-sync reject requests; resync the clock first.
- Full disk: clear the spool directory, then restart pod-sync.

### Capacity limits

The pod-sync service is sized for 1500 requests per minute per depot. Above 2000 requests per minute it starts to refuse new work, and the customer desk is paged after 25 seconds of refusals.

### Maintenance windows

Planned work on pod-sync happens on Sunday between 03:00 and 04:00. The customer desk announces it 5 days ahead.

### Backups

A snapshot of pod-sync is taken every 2 hours and kept for 35 days. A restore takes about 60 minutes and is started with `mfc-ctl restore pod-sync --depot KY --snapshot latest`.

### Escalation

If a restart does not help within 30 minutes, the on-call engineer calls the customer desk and then the depot manager.


## Driver handheld app (driver-app)

The driver handheld app runs as the service `driver-app` and listens on port 7480. Its owner is the fleet engineer.

### Start and stop

```
mfc-ctl restart driver-app --depot KY
mfc-ctl status driver-app
```

A restart takes about 45 seconds. Use the `--depot` flag with the two-letter depot code; without it the command refuses to run.

### Health checks

The health endpoint must answer within 5 seconds. If it fails 2 times in a row the monitor pages the on-call engineer. The service queue is healthy below 350 messages, and the disk alert fires at 90 percent usage.

### Known failures

- Stuck queue: the driver-app queue stops draining after a network drop; restart the service.
- Clock drift: a drift of more than 2 seconds makes driver-app reject requests; resync the clock first.
- Full disk: clear the spool directory, then restart driver-app.

### Capacity limits

The driver-app service is sized for 1050 requests per minute per depot. Above 1400 requests per minute it starts to refuse new work, and the fleet engineer is paged after 5 seconds of refusals.

### Maintenance windows

Planned work on driver-app happens on Tuesday between 03:00 and 04:00. The fleet engineer announces it 2 days ahead.

### Backups

A snapshot of driver-app is taken every 10 hours and kept for 7 days. A restore takes about 90 minutes and is started with `mfc-ctl restore driver-app --depot KY --snapshot latest`.

### Escalation

If a restart does not help within 45 minutes, the on-call engineer calls the fleet engineer and then the depot manager.
