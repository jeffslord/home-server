docker exec mc-server rcon-cli /say SERVER RESTART IN 5 MINUTES
sleep 3m
docker exec mc-server rcon-cli /say SERVER RESTART IN 2 MINUTES
sleep 1m
docker exec mc-server rcon-cli /say SERVER RESTART IN 1 MINUTES
sleep 1m
docker exec mc-server rcon-cli /say SERVER RESTARTING
sleep 5s
docker compose -f /home/jeff/git/home-server/games/minecraft/cobbleverse_1.7.2/docker-compose.yml restart