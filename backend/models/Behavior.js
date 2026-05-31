const mongoose = require("mongoose");

const behaviorSchema = new mongoose.Schema(
  {
    userId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: "User",
      required: true,
      index: true,
    },
    postId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: "Job",
      required: true,
      index: true,
    },
    action: {
      type: String,
      enum: ["view", "like", "save", "apply", "share", "comment"],
      required: true,
      index: true,
    },
    duration: {
      type: Number,
      default: 0,
      min: 0,
    },
  },
  {
    timestamps: { createdAt: true, updatedAt: false },
  }
);

behaviorSchema.index({ userId: 1, postId: 1, action: 1, createdAt: -1 });

module.exports = mongoose.model("Behavior", behaviorSchema);