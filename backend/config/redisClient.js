const Redis = require("ioredis");

let hasConnectedRedis = false;

const redisClient = new Redis({
  host: process.env.REDIS_HOST || "127.0.0.1",
  port: Number(process.env.REDIS_PORT || 6379),
  maxRetriesPerRequest: null,
  lazyConnect: true,
  retryStrategy: () => null,
  connectTimeout: Number(process.env.REDIS_CONNECT_TIMEOUT || 1000)
});

redisClient.on("error", (err) => {
  if (hasConnectedRedis) {
    console.error("❌ Redis Error:", err.message || err);
  }
});

if (typeof redisClient.setEx !== "function" && typeof redisClient.setex === "function") {
  redisClient.setEx = redisClient.setex.bind(redisClient);
}

const connectRedis = async () => {
  try {
    if (redisClient.status === "ready") {
      hasConnectedRedis = true;
      console.log("Redis connected");
      return;
    }

    await redisClient.connect();
    hasConnectedRedis = true;
    console.log("Redis connected");
  } catch (err) {
    hasConnectedRedis = false;
    try {
      redisClient.disconnect();
    } catch (_) {
      // Ignore disconnect cleanup errors.
    }
  }
};

module.exports = redisClient;
module.exports.redisClient = redisClient;
module.exports.connectRedis = connectRedis;