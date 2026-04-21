const mongoose = require("mongoose");

const swipeSchema = new mongoose.Schema(
  {
    candidateId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: "User",
      required: true,
      index: true
    },

    jobId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: "Job",
      required: true,
      index: true
    },

    action: {
      type: String,
      enum: ["like", "dislike"],
      required: true
    }
  },
  {
    timestamps: true
  }
);

// 🔥 Prevent duplicate swipes (critical)
swipeSchema.index({ candidateId: 1, jobId: 1 }, { unique: true });

module.exports = mongoose.model("Swipe", swipeSchema);