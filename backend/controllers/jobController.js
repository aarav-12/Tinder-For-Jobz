const { getJobFeed } = require("../services/feedService")

async function getFeed(req, res) {

  const userId = req.user.userId

  const jobs = await getJobFeed(userId)

  res.json(jobs)
}

module.exports = { getFeed }