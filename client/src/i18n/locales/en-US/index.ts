import common from "./common.json";
import navigation from "./navigation.json";
import auth from "./auth.json";
import dashboard from "./dashboard.json";
import restApi from "./restApi.json";
import grpc from "./grpc.json";
import gateways from "./gateways.json";
import users from "./users.json";
import tools from "./tools.json";
import resources from "./resources.json";
import mcpServer from "./mcpServer.json";

export default {
  ...common,
  ...navigation,
  ...auth,
  ...dashboard,
  ...restApi,
  ...grpc,
  ...gateways,
  ...users,
  ...tools,
  ...resources,
  ...mcpServer,
};
