const buildPreferenceProfile = (swipes) => {
  const liked = new Set();
  const disliked = new Set();

  for (const swipe of swipes) {
    if (swipe.action === "like") {
      liked.add(swipe.jobId.toString());
    } else if (swipe.action === "dislike") {
      disliked.add(swipe.jobId.toString());
    }
  }

  return {
    liked,
    disliked
  };
};

module.exports = { buildPreferenceProfile };