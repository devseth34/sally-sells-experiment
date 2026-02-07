from app.agent import SallyEngine

# 1. Initialize the Experiment (Simulate a user starting a chat)
print("--- INITIALIZING SESSION ---")
engine = SallyEngine(session_id="test-session-001", pre_conviction_score=5)
print(f"Current State: {engine.session.current_phase}")

# 2. Simulate the Conversation Loop
user_inputs = [
    "Hi, I'm interested in your services.",  # Should move to Problem Awareness
    "Yeah, we have a lead gen issue.",       # Should move to Consequence
    "It's costing us $10k a month.",         # Should move to Solution Awareness
    "I need a fix fast.",                    # Should move to Ownership
    "I'm ready to buy."                      # Should move to Terminated
]

print("\n--- STARTING SIMULATION ---")
for text in user_inputs:
    print(f"\nUser says: '{text}'")
    engine.process_input(text)
    # The engine print statement will show the transition
    
print("\n--- SIMULATION COMPLETE ---")