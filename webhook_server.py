from flask import Flask, request, jsonify
import stripe
import pymongo
from dotenv import load_dotenv
from datetime import datetime
import os

# Load environment variables from .env file
load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

# MongoDB connection
mongo_client = pymongo.MongoClient("mongodb://localhost:27017/")
db = mongo_client["marketplace_bot"]
users = db["users"]
sessions = db["stripe_sessions"]  # For duplicate session protection

# Flask app setup
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except stripe.error.SignatureVerificationError:
        return '❌ Invalid signature', 400
    except Exception as e:
        print(f"⚠️ Error parsing webhook: {e}")
        return '❌ Bad request', 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        if session['payment_status'] == 'paid':
            metadata = session.get('metadata', {})
            if 'telegram_id' in metadata and 'amount' in metadata:
                try:
                    telegram_id = int(metadata['telegram_id'])
                    amount = float(metadata['amount'])
                    session_id = session['id']

                    # Prevent duplicate processing
                    if sessions.find_one({"session_id": session_id}):
                        return jsonify({"status": "ignored - duplicate"}), 200

                    # Log this session
                    sessions.insert_one({"session_id": session_id})

                    # Update wallet in DB
                    users.update_one(
                        {"telegram_id": telegram_id},
                        {"$inc": {"wallet": amount}}
                    )

                    print(f"✅ Wallet credited: Telegram ID {telegram_id}, Amount ${amount:.2f}")
                except Exception as e:
                    print(f"❌ Error processing wallet update: {e}")
                    return jsonify({"status": "error"}), 500
            else:
                print("⚠️  Received session without required metadata. Ignored.")

    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    app.run(port=5000)
