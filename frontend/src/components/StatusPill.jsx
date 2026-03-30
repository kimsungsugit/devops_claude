import { classNames } from '../utils/ui'

const StatusPill = ({ tone = 'neutral', children }) => (
  <span className={classNames('pill', `pill-${tone}`)}>{children}</span>
)

export default StatusPill
