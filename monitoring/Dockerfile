# ============================================================================
# FILE: monitoring/Dockerfile
# PURPOSE: Combines Prometheus and Grafana into a single container 
#          managed by supervisord.
# ============================================================================

FROM alpine:3.19

# Install supervisor, prometheus, and grafana
RUN apk add --no-cache supervisor prometheus grafana

# Create necessary directories
RUN mkdir -p /var/log/supervisor /etc/prometheus /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards /var/lib/grafana/dashboards

# Copy supervisord config
COPY supervisord.conf /etc/supervisord.conf

# Copy Prometheus config
COPY prometheus/prometheus.yml /etc/prometheus/prometheus.yml

# Copy Grafana config & provisioning
COPY grafana/grafana.ini /etc/grafana/grafana.ini
COPY grafana/provisioning/ /etc/grafana/provisioning/

# Note: Any custom dashboards should be copied to /var/lib/grafana/dashboards if defined in provisioning

EXPOSE 3000 9090

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]
