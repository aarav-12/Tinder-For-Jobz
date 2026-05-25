const Redis = require("ioredis");

const redisClient = new Redis({
  host: process.env.REDIS_HOST || "127.0.0.1",
  port: Number(process.env.REDIS_PORT || 6379),
  maxRetriesPerRequest: null
});

redisClient.on("error", (err) => {
  console.error("❌ Redis Error:", err);
});

if (typeof redisClient.setEx !== "function" && typeof redisClient.setex === "function") {
  redisClient.setEx = redisClient.setex.bind(redisClient);
}

const connectRedis = async () => {
  try {
    if (redisClient.status === "ready") {
      console.log("Redis connected");
      return;
    }

    await new Promise((resolve, reject) => {
      const cleanup = () => {
        redisClient.off("ready", onReady);
        redisClient.off("error", onError);
      };

      const onReady = () => {
        cleanup();
        resolve();
      };

      const onError = (err) => {
        cleanup();
        reject(err);
      };

      redisClient.once("ready", onReady);
      redisClient.once("error", onError);
    });

    console.log("Redis connected");
  } catch (err) {
    console.error("Redis connection failed:", err);
  }
};

module.exports = redisClient;
module.exports.redisClient = redisClient;
module.exports.connectRedis = connectRedis;