const { redisClient } = require("../config/redisClient");

const MAX_TOKENS = 10;
const REFILL_RATE = 1;

const rateLimiter = async (req, res, next) => {
  try {
    const userId =
      req.query.candidateId ||
      req.body.candidateId;

    if (!userId) {
      return res.status(400).json({
        success: false,
        message: "candidateId required"
      });
    }

    const key = `ratelimit:${userId}`;

    const existingBucket = await redisClient.get(key);

    let bucket = {
      tokens: MAX_TOKENS,
      lastRefill: Date.now()
    };

    if (existingBucket) {
      bucket = JSON.parse(existingBucket);
    }

    const now = Date.now();

    const secondsPassed =
      (now - bucket.lastRefill) / 1000;

    const refillAmount =
      secondsPassed * REFILL_RATE;

    bucket.tokens = Math.min(
      MAX_TOKENS,
      bucket.tokens + refillAmount
    );

    bucket.lastRefill = now;

    if (bucket.tokens < 1) {
      return res.status(429).json({
        success: false,
        message: "Too many requests"
      });
    }

    bucket.tokens -= 1;

    await redisClient.setEx(
      key,
      60,
      JSON.stringify(bucket)
    );

    next();

  } catch (err) {
    console.error("Rate limiter failed:", err);

    next();
  }
};

module.exports = rateLimiter;