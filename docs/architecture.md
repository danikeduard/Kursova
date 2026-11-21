# Architecture

LinguaPath is a Flask application factory with blueprints for authentication
and pages/API routes. SQLAlchemy persists accounts, conversation messages,
ratings, topic mastery, error observations, feedback, and API metrics. The
chat endpoint submits evaluator and tutor calls concurrently; the tutor sees
ratings from before the current turn, while the evaluator updates ratings and
topic mastery afterward.

`ChatTurn` is the audit boundary for one learner request. It links the user
and assistant messages, provider/model, evaluator status, tutor status,
failure reason, and timestamps. `ApiMetric` records usage, estimated cost,
retry count, and success/failure independently for evaluator and tutor calls.

The adaptation pipeline has four deterministic boundaries:

1. the evaluator returns a validated observation for grammar, vocabulary, and
   writing;
2. the rating service updates the three CEFR skill states;
3. the learning service updates topic mastery and uncertainty from grounded
   error/strength evidence;
4. the pedagogical policy selects one explainable next action for the tutor.

The LLM never writes ratings or mastery directly. Jinja renders the shell and
vanilla JavaScript calls JSON endpoints without injecting learner or model
content as HTML.
